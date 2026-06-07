"""Small retry boundary for transient Supabase transport failures."""
import time

import httpx
from fastapi import HTTPException


def execute_query(query, attempts: int = 3):
    for attempt in range(attempts):
        try:
            return query.execute()
        except httpx.TransportError:
            if attempt + 1 == attempts:
                raise HTTPException(
                    status_code=503,
                    detail="Catalog temporarily unavailable",
                )
            time.sleep(0.25 * (2 ** attempt))
