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
