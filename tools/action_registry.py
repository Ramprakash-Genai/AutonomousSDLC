def navigate(page, data):
   page.goto(data.get("value"))

def input_text(page, data):
   page.locator(data.get("locator")).fill(data.get("value"))

def click(page, data):
   page.locator(data.get("locator")).click()

ACTION_MAP = {
   "navigate": navigate,
   "input": input_text,
   "click": click
}