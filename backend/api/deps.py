import os
from threading import local

from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()
_clients = local()


def get_supabase() -> Client:
    """Reuse a client within one worker thread, never across concurrent threads."""
    client = getattr(_clients, "supabase", None)
    if client is None:
        client = create_client(
            os.environ["SUPABASE_URL"],
            os.environ["SUPABASE_SERVICE_KEY"],
        )
        _clients.supabase = client
    return client
