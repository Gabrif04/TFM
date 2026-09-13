"""Optional live browser check. Start the app on localhost:8501 first; requires Selenium."""
from pathlib import Path
from selenium import webdriver
from selenium.common.exceptions import StaleElementReferenceException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.common.action_chains import ActionChains

options = Options()
options.add_argument("--headless=new")
options.add_argument("--window-size=430,932")
driver = webdriver.Chrome(options=options)
wait = WebDriverWait(driver, 40, ignored_exceptions=(StaleElementReferenceException,))
output = Path(__file__).resolve().parents[2] / "scratch"

try:
    # Load at phone width from the beginning so the test exercises Streamlit's
    # mobile navigation and initial websocket/data load.
    driver.get("http://localhost:8501")
    wait.until(lambda d: len(d.find_elements(By.CSS_SELECTOR, '[data-testid="stMetricValue"]')) == 3)
    wait.until(lambda d: len(d.find_elements(By.CSS_SELECTOR, ".main-svg")) >= 2)
    assert not driver.find_elements(By.CSS_SELECTOR, '[data-testid="stException"]')
    viewport = driver.execute_script("return window.innerWidth")
    page_width = driver.execute_script("return document.documentElement.scrollWidth")
    assert page_width <= viewport + 1, f"Horizontal overflow on mobile: {page_width}px > {viewport}px"
    driver.save_screenshot(str(output / "dashboard_mobile_overview.png"))
    driver.set_window_size(1440, 1100)
    driver.refresh()
    wait.until(lambda d: len(d.find_elements(By.CSS_SELECTOR, '[data-testid="stMetricValue"]')) == 3)
    driver.save_screenshot(str(output / "dashboard_overview.png"))
    driver.find_element(By.PARTIAL_LINK_TEXT, "Ranking").click()
    wait.until(lambda d: len(d.find_elements(By.CSS_SELECTOR, '[data-testid="stDataFrame"] canvas')) > 0)
    wait.until(lambda d: len(d.find_elements(By.CSS_SELECTOR, ".main-svg")) > 0)
    driver.save_screenshot(str(output / "dashboard_ranking.png"))
    canvas = driver.find_element(By.CSS_SELECTOR, '[data-testid="stDataFrame"] canvas')
    driver.execute_script('arguments[0].scrollIntoView({block:"center"})', canvas)
    ActionChains(driver).move_to_element_with_offset(
        canvas, -canvas.size["width"] / 2 + 15, -canvas.size["height"] / 2 + 52
    ).click().perform()
    button = wait.until(lambda d: d.find_element(By.XPATH, "//button[contains(., 'Abrir perfil seleccionado')]"))
    button.click()
    wait.until(lambda d: "Encuentra a tu" in d.find_element(By.TAG_NAME, "body").text)
    wait.until(lambda d: len(d.find_elements(By.CSS_SELECTOR, '[data-testid="stMetricValue"]')) >= 4)
    wait.until(lambda d: "Erling Haaland" in d.find_element(By.TAG_NAME, "body").text)
    assert not driver.find_elements(By.CSS_SELECTOR, '[data-testid="stException"]')
    identity = wait.until(lambda d: d.find_element(By.CSS_SELECTOR, ".player-identity"))
    wait.until(lambda d: all(d.execute_script(
        "return arguments[0].complete && arguments[0].naturalWidth > 0", image
    ) for image in d.find_elements(By.CSS_SELECTOR, ".player-identity img")))
    driver.execute_script('arguments[0].scrollIntoView({block:"start"})', identity)
    driver.save_screenshot(str(output / "dashboard_profile.png"))
    driver.set_window_size(430, 932)
    wait.until(lambda d: "Erling Haaland" in d.find_element(By.TAG_NAME, "body").text)
    wait.until(lambda d: len(d.find_elements(By.CSS_SELECTOR, ".valuation-circle")) == 2)
    assert not driver.find_elements(By.CSS_SELECTOR, '[data-testid="stException"]')
    driver.save_screenshot(str(output / "dashboard_mobile.png"))
    print("PASS: CSV overview, ranking selection to exact profile, desktop and mobile rendering.")
except Exception:
    driver.save_screenshot(str(output / "dashboard_browser_error.png"))
    print(driver.find_element(By.TAG_NAME, "body").text[:4000].encode("ascii", "backslashreplace").decode())
    raise
finally:
    driver.quit()
