import asyncio
from pathlib import Path
from app.services.capture import capture_page

async def main():
    result = await capture_page("https://www.uswitch.com/mobiles/")
    path = Path("uswitch_rendered.html")
    path.write_text(result.html, encoding="utf-8")
    print("Page title:", result.page_title)
    print("Final URL:", result.final_url)
    print("HTML size:", len(result.html), "characters")
    print("Saved:", path.resolve())

asyncio.run(main())
