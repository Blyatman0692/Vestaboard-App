import psycopg
from sonos_app.token import SonosToken


PLAYBACK_METADATA_NAMESPACE = "playbackMetadata"


class PostgresDataStore:
    def __init__(self, db_url, user_key):
        self.db_url = db_url
        self.user_key = user_key

    @staticmethod
    def _isoformat(value):
        return value.isoformat() if value else None

    @staticmethod
    def _ensure_playback_target_table(cur):
        cur.execute(
            """
            create table if not exists sonos_playback_target (
              user_key text primary key,
              household_id text not null,
              player_id text not null,
              group_id text
            )
            """
        )

    def save_playback_target(self, household_id: str, player_id: str):
        """Select a speaker, keeping its cached group only if the target is unchanged."""
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                self._ensure_playback_target_table(cur)
                cur.execute(
                    """
                    insert into sonos_playback_target (user_key, household_id, player_id)
                    values (%s, %s, %s)
                    on conflict (user_key) do update set
                      household_id = excluded.household_id,
                      player_id = excluded.player_id,
                      group_id = case
                        when sonos_playback_target.household_id = excluded.household_id
                         and sonos_playback_target.player_id = excluded.player_id
                        then sonos_playback_target.group_id
                        else null
                      end
                    returning household_id, player_id, group_id
                    """,
                    (self.user_key, household_id, player_id),
                )
                household_id, player_id, group_id = cur.fetchone()

        return {
            "household_id": household_id,
            "player_id": player_id,
            "group_id": group_id,
        }

    def load_playback_target(self):
        """Load the selected speaker even when no current group is known."""
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                self._ensure_playback_target_table(cur)
                cur.execute(
                    """
                    select household_id, player_id, group_id
                    from sonos_playback_target
                    where user_key = %s
                    """,
                    (self.user_key,),
                )
                row = cur.fetchone()

        if row is None:
            return None

        household_id, player_id, group_id = row
        return {
            "household_id": household_id,
            "player_id": player_id,
            "group_id": group_id,
        }

    def update_playback_target_group(
        self, household_id: str, player_id: str, group_id: str | None
    ) -> bool:
        """Cache discovery and retire other subscriptions if the target is unchanged."""
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                self._ensure_playback_target_table(cur)
                cur.execute(
                    """
                    update sonos_playback_target
                    set group_id = %s
                    where user_key = %s and household_id = %s and player_id = %s
                    """,
                    (group_id, self.user_key, household_id, player_id),
                )
                if cur.rowcount != 1:
                    return False

                self._ensure_subscriptions_table(cur)
                cur.execute(
                    """
                    update sonos_subscriptions
                    set active = false, updated_at = now()
                    where user_key = %s and namespace = %s and active = true
                      and group_id is distinct from %s
                    """,
                    (self.user_key, PLAYBACK_METADATA_NAMESPACE, group_id),
                )
        return True

    @staticmethod
    def _ensure_subscriptions_table(cur):
        cur.execute(
            """
            create table if not exists sonos_subscriptions (
              user_key text not null,
              group_id text not null,
              namespace text not null,
              active boolean not null default true,
              created_at timestamp with time zone not null default now(),
              updated_at timestamp with time zone not null default now(),
              last_subscribed_at timestamp with time zone not null default now(),
              primary key (user_key, group_id, namespace)
            )
            """
        )

    @staticmethod
    def _ensure_groups_subscriptions_table(cur):
        cur.execute(
            """
            create table if not exists sonos_groups_subscriptions (
              user_key text not null,
              household_id text not null,
              last_subscribed_at timestamp with time zone not null default now(),
              primary key (user_key, household_id)
            )
            """
        )

    def save_groups_subscription(self, household_id: str):
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                self._ensure_groups_subscriptions_table(cur)
                cur.execute(
                    """
                    insert into sonos_groups_subscriptions (user_key, household_id)
                    values (%s, %s)
                    on conflict (user_key, household_id) do update set
                      last_subscribed_at = now()
                    returning last_subscribed_at
                    """,
                    (self.user_key, household_id),
                )
                last_subscribed_at, = cur.fetchone()
        return {
            "household_id": household_id,
            "namespace": "groups",
            "last_subscribed_at": self._isoformat(last_subscribed_at),
        }

    def groups_subscription_due(self, household_id: str, renew_after_seconds: int) -> bool:
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                self._ensure_groups_subscriptions_table(cur)
                cur.execute(
                    """
                    select last_subscribed_at <= now() - (%s * interval '1 second')
                    from sonos_groups_subscriptions
                    where user_key = %s and household_id = %s
                    """,
                    (renew_after_seconds, self.user_key, household_id),
                )
                row = cur.fetchone()
        return row is None or row[0]

    def save_tokens(self, tokens: dict[str, str]):
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    insert into sonos_tokens (user_key, access_token, refresh_token, expires_in, scope, updated_at)
                    values (%s, %s, %s, %s, %s, now())
                    on conflict (user_key) do update set
                      access_token = excluded.access_token,
                      refresh_token = excluded.refresh_token,
                      expires_in = excluded.expires_in,
                      scope = excluded.scope,
                      updated_at = now()
                    """,
                    (
                        self.user_key,
                        tokens["access_token"],
                        tokens["refresh_token"],
                        tokens.get("expires_in"),
                        tokens.get("scope")
                    )
                )
                conn.commit()

    def load_tokens(self):
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select access_token,
                           refresh_token,
                           expires_in,
                           scope,
                           updated_at
                    from sonos_tokens
                    where user_key = %s
                    """,
                    (self.user_key,),
                )
                row = cur.fetchone()

        if not row:
            return None

        access_token, refresh_token, expires_in, scope, updated_at = row
        return SonosToken(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=expires_in,
            scope=scope,
            updated_at=updated_at.isoformat() if updated_at else None
        )

    def save_playback_metadata_subscription(self, group_id: str):
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                self._ensure_subscriptions_table(cur)
                cur.execute(
                    """
                    insert into sonos_subscriptions (
                      user_key,
                      group_id,
                      namespace,
                      active,
                      created_at,
                      updated_at,
                      last_subscribed_at
                    )
                    values (%s, %s, %s, true, now(), now(), now())
                    on conflict (user_key, group_id, namespace) do update set
                      active = true,
                      updated_at = now(),
                      last_subscribed_at = now()
                    returning group_id,
                              namespace,
                              active,
                              created_at,
                              updated_at,
                              last_subscribed_at
                    """,
                    (self.user_key, group_id, PLAYBACK_METADATA_NAMESPACE),
                )
                row = cur.fetchone()
                conn.commit()

        group_id, namespace, active, created_at, updated_at, last_subscribed_at = row
        return {
            "group_id": group_id,
            "namespace": namespace,
            "active": active,
            "created_at": self._isoformat(created_at),
            "updated_at": self._isoformat(updated_at),
            "last_subscribed_at": self._isoformat(last_subscribed_at),
        }

    def invalidate_playback_metadata_subscription(self, group_id: str):
        """Retire a gone group and clear its cached ID without losing the speaker."""
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                self._ensure_playback_target_table(cur)
                self._ensure_subscriptions_table(cur)
                cur.execute(
                    """
                    update sonos_playback_target set group_id = null
                    where user_key = %s and group_id = %s
                    """,
                    (self.user_key, group_id),
                )
                cur.execute(
                    """
                    update sonos_subscriptions set active = false, updated_at = now()
                    where user_key = %s and group_id = %s and namespace = %s
                      and active = true
                    """,
                    (self.user_key, group_id, PLAYBACK_METADATA_NAMESPACE),
                )

    def list_playback_metadata_subscriptions(self):
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                self._ensure_subscriptions_table(cur)
                cur.execute(
                    """
                    select group_id,
                           namespace,
                           active,
                           created_at,
                           updated_at,
                           last_subscribed_at
                    from sonos_subscriptions
                    where user_key = %s
                      and namespace = %s
                    order by updated_at desc
                    """,
                    (self.user_key, PLAYBACK_METADATA_NAMESPACE),
                )
                rows = cur.fetchall()
                conn.commit()

        return [
            {
                "group_id": group_id,
                "namespace": namespace,
                "active": active,
                "created_at": self._isoformat(created_at),
                "updated_at": self._isoformat(updated_at),
                "last_subscribed_at": self._isoformat(last_subscribed_at),
            }
            for group_id, namespace, active, created_at, updated_at, last_subscribed_at in rows
        ]

    def list_due_playback_metadata_subscriptions(self, renew_after_seconds: int):
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                self._ensure_subscriptions_table(cur)
                cur.execute(
                    """
                    select group_id,
                           namespace,
                           active,
                           created_at,
                           updated_at,
                           last_subscribed_at
                    from sonos_subscriptions
                    where user_key = %s
                      and namespace = %s
                      and active = true
                      and last_subscribed_at <= now() - (%s * interval '1 second')
                    order by last_subscribed_at asc
                    """,
                    (
                        self.user_key,
                        PLAYBACK_METADATA_NAMESPACE,
                        renew_after_seconds,
                    ),
                )
                rows = cur.fetchall()
                conn.commit()

        return [
            {
                "group_id": group_id,
                "namespace": namespace,
                "active": active,
                "created_at": self._isoformat(created_at),
                "updated_at": self._isoformat(updated_at),
                "last_subscribed_at": self._isoformat(last_subscribed_at),
            }
            for group_id, namespace, active, created_at, updated_at, last_subscribed_at in rows
        ]

    def clear_tokens(self):
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    delete from sonos_tokens
                    where user_key = %s
                    """,
                    (self.user_key,),
                )
                conn.commit()

    def save_oauth_state(self, state: str):
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    insert into oauth_states (state, created_at)
                    values (%s, now())
                    on conflict (state) do nothing
                    """,
                    (state,),
                )
                conn.commit()

    def consume_oauth_state(self, state: str) -> bool:
        """
        Return True if state existed and was deleted, False otherwise.
        """
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    delete from oauth_states
                    where state = %s
                    returning state
                    """,
                    (state,),
                )
                row = cur.fetchone()
                conn.commit()

        return row is not None
