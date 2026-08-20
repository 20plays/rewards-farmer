from selenium.common.exceptions import WebDriverException
from selenium import webdriver

GHOST_TAB_URL = "https://ntp.msn.com/edge/ntp?locale=en-US&title=New%20tab&fre=1&dsp=1&sp=Bing&feed_dis=always&en_widget_reg=false&prerender=1&PC=U531"

class TabUtils:
	def __init__(self, driver: webdriver.Edge):
		self.driver = driver
		self.problematic_tabs = set()

	def switch_to_other_tab(self):
		current_window = self.driver.current_window_handle

		for handle in self.driver.window_handles:
			if handle != current_window and handle not in self.problematic_tabs:
				self.driver.switch_to.window(handle)

				if self.driver.current_url == GHOST_TAB_URL: continue
				return

	def close_all_other_tabs(self, exceptions: list[str] = None):
		if exceptions is None:
			exceptions = [self.driver.current_window_handle]

		switch_back_to = exceptions[0]

		for handle in self.driver.window_handles:
			if handle not in exceptions and handle not in self.problematic_tabs:
				self.driver.switch_to.window(handle)

				if self.driver.current_url == GHOST_TAB_URL: continue

				try: self.driver.close()
				except WebDriverException:
					print(f"[WARNING] Could not close tab with handle {handle}.")
					self.problematic_tabs.add(handle)
					pass

		self.driver.switch_to.window(switch_back_to)