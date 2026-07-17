
import asyncio, json
from services.providers.ghunt.provider import search

async def main():
    results, errors = await search('siddhantadiverma@gmail.com')
    print(json.dumps({'results': results, 'errors': errors}, indent=2, default=str))

asyncio.run(main())
