import psycopg
from sonos_app.token import SonosToken

class PostgresDataStore:
    def __init__(self, db_url, user_key):
        self.db_url = db_url
        self.user_key = user_key

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
