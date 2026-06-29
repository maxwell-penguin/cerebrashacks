import asyncio
from playwright.async_api import async_playwright
import os

async def main():
    artifact_dir = "/Users/max/.gemini/antigravity-ide/brain/afd2dcc4-21ac-4e2c-9c2e-331192d8edcc"
    os.makedirs(artifact_dir, exist_ok=True)
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        # Create a page with default size
        page = await browser.new_page(viewport={"width": 1280, "height": 800})
        
        print("Navigating to local dev server http://localhost:5176/...")
        await page.goto("http://localhost:5176/")
        await page.wait_for_timeout(1000)
        
        # Take landing page screenshot
        landing_path = os.path.join(artifact_dir, "landing_page_polish.png")
        await page.screenshot(path=landing_path)
        print(f"Saved landing page screenshot to {landing_path}")
        
        # Click Get Started
        print("Clicking 'Get Started' button...")
        await page.locator("button:has-text('Get Started')").click()
        await page.wait_for_timeout(2000)
        
        # Take workspace screenshot
        workspace_path = os.path.join(artifact_dir, "workspace_idle_polish.png")
        await page.screenshot(path=workspace_path)
        print(f"Saved workspace screenshot to {workspace_path}")
        
        await browser.close()
        print("Done!")

if __name__ == "__main__":
    asyncio.run(main())
