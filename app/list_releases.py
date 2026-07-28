"""Utilitário pra descobrir o SENDFLOW_RELEASE_ID certo.

Uso: python -m app.list_releases
(precisa de SENDFLOW_API_TOKEN já preenchido no .env)
"""
import asyncio

from app import sendflow_client


async def main() -> None:
    releases = await sendflow_client.list_releases()
    for r in releases:
        print(f"{r.get('id')}  —  {r.get('name')}")


if __name__ == "__main__":
    asyncio.run(main())
