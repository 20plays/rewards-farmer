import os
import sys
import unittest

from selenium.common.exceptions import StaleElementReferenceException, TimeoutException
from selenium.webdriver.common.keys import Keys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import rewards_tasks


class FakeSwitch:
	def __init__(self, driver):
		self.driver = driver

	def window(self, handle):
		self.driver.actions.append(("switch", handle))
		self.driver.current_window_handle = handle
		self.driver.current_url = self.driver.urls[handle]


class FakeDriver:
	def __init__(self, handles, urls, current):
		self.window_handles = list(handles)
		self.urls = dict(urls)
		self.current_window_handle = current
		self.current_url = self.urls[current]
		self.capabilities = {"platformName": "linux"}
		self.actions = []
		self.switch_to = FakeSwitch(self)

	def get(self, url):
		self.actions.append(("get", url))
		self.current_url = url


class FakeTabs:
	def __init__(self, driver):
		self.driver = driver
		self.calls = []

	def close_all_other_tabs(self, exceptions=None):
		self.calls.append(("close", list(exceptions or [])))
		self.driver.actions.append(("close", tuple(exceptions or [])))

	def ensure_focus(self):
		self.calls.append(("focus",))
		self.driver.actions.append(("focus",))


class FakeSearchBar:
	def __init__(self, value="old query", stale_once=False):
		self.value = value
		self.stale_once = stale_once
		self.sent = []

	def send_keys(self, *keys):
		if self.stale_once:
			self.stale_once = False
			raise StaleElementReferenceException("rerendered")

		self.sent.append(keys)

		if keys[-1] == Keys.BACKSPACE:
			self.value = ""

	def get_attribute(self, name):
		if name == "value":
			return self.value
		return None


class FakeElements:
	def get_bing_search_bar(self):
		raise AssertionError("wait_for_element should not execute the getter in this unit test")


class TestRewardsContextRecovery(unittest.TestCase):
	def make_task(self, driver, rewards_handle="rewards"):
		task = rewards_tasks.RewardsTaskUtils.__new__(rewards_tasks.RewardsTaskUtils)
		task.driver = driver
		task.rewards_window_handle = rewards_handle
		task.tab_utils = FakeTabs(driver)
		return task

	def test_returns_to_rewards_before_closing_child_tabs(self):
		driver = FakeDriver(
			handles=["rewards", "bing"],
			urls={
				"rewards": "https://rewards.bing.com/earn",
				"bing": "https://www.bing.com/search?q=test",
			},
			current="bing",
		)
		task = self.make_task(driver)

		task.restore_rewards_context(force_home=True)

		self.assertEqual(driver.actions[0], ("switch", "rewards"))
		self.assertEqual(driver.actions[1], ("close", ("rewards",)))
		self.assertEqual(driver.actions[2], ("get", rewards_tasks.REWARDS_HOME_URL))
		self.assertEqual(task.rewards_window_handle, "rewards")

	def test_salvages_a_surviving_tab_if_rewards_tab_was_closed(self):
		driver = FakeDriver(
			handles=["survivor"],
			urls={"survivor": "https://www.bing.com/search?q=test"},
			current="survivor",
		)
		task = self.make_task(driver, rewards_handle="missing")

		task.restore_rewards_context()

		self.assertEqual(task.rewards_window_handle, "survivor")
		self.assertIn(("get", rewards_tasks.REWARDS_HOME_URL), driver.actions)


class TestSearchClearing(unittest.TestCase):
	def make_task(self, bars):
		driver = type("Driver", (), {"capabilities": {"platformName": "linux"}})()
		task = rewards_tasks.RewardsTaskUtils.__new__(rewards_tasks.RewardsTaskUtils)
		task.driver = driver
		task.elements = FakeElements()
		bars = iter(bars)
		task.wait_for_element = lambda getter: next(bars)
		return task

	def test_clears_the_input_directly_with_select_all_and_backspace(self):
		bar = FakeSearchBar()
		task = self.make_task([bar])

		task.clear_bing_search_query()

		self.assertEqual(bar.sent, [(Keys.CONTROL, "a", Keys.BACKSPACE)])
		self.assertEqual(bar.value, "")

	def test_retries_if_the_search_input_rerenders(self):
		stale = FakeSearchBar(stale_once=True)
		fresh = FakeSearchBar()
		task = self.make_task([stale, fresh])

		task.clear_bing_search_query()

		self.assertEqual(fresh.value, "")


class TestTaskOutcomeMessages(unittest.TestCase):
	def test_timeout_is_not_reported_as_a_missing_ui_variant(self):
		task = rewards_tasks.RewardsTaskUtils.__new__(rewards_tasks.RewardsTaskUtils)
		task.complete_bing_daily_set = lambda: (_ for _ in ()).throw(TimeoutException())
		task.complete_explore_on_bing_tasks = lambda: None
		task.complete_visual_search = lambda: None
		task.complete_misc_cards = lambda: None
		task.complete_required_searches = lambda: None
		task.claim_bonus_points = lambda: None
		task.restore_rewards_context = lambda force_home=False: None

		with self.assertLogs(rewards_tasks.logger, level="WARNING") as logged:
			task.complete_all_tasks()

		message = "\n".join(logged.output)
		self.assertIn("timed out waiting for the current UI", message)
		self.assertNotIn("Bing daily set: not available in this UI variant", message)


if __name__ == "__main__":
	unittest.main()
