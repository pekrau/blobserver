"Some utilities for the tests."

import json
import os
import unittest

import selenium.webdriver


class BrowserTestCase(unittest.TestCase):
    "Browser driver setup."

    def setUp(self):
        self.settings = get_settings()
        self.driver = get_browser_driver(self.settings["BROWSER"])

    def tearDown(self):
        self.driver.close()


def get_settings():
    """Get the settings from
    1) default
    2) settings file
    3) environment variables
    """
    result = {
        "BROWSER": "Chrome",
        "BASE_URL": "http://127.0.0.1:5009/",
        "USERNAME": None,
        "PASSWORD": None
    }

    try:
        with open("settings.json", "rb") as infile:
            result.update(json.load(infile))
    except IOError:
        pass
    for key in result:
        try:
            result[key] = os.environ[key]
        except KeyError:
            pass
    for key in result:
        if result.get(key) is None:
            raise KeyError(f"Missing {key} value in settings.")
    return result

def get_browser_driver(name):
    "Return the Selenium driver for the browser given by name."
    if name == "Chrome":
        return selenium.webdriver.Chrome()
    elif name == "Firefox":
        return selenium.webdriver.Firefox()
    elif name == "Edge":
        return selenium.webdriver.Edge()
    elif name == "Safari":
        return selenium.webdriver.Safari()
    else:
        raise ValueError(f"Unknown browser driver '{name}'.")
