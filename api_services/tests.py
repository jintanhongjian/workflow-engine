from django.test import SimpleTestCase

from api_services.skills.root_skill_manager import _normalize_requirements


class RootSkillManagerRegressionTests(SimpleTestCase):
    def test_normalize_requirements_filters_block_markers(self):
        raw = "CODE_START requests TEST_START"
        normalized = _normalize_requirements(raw)
        self.assertEqual(normalized, "requests")

    def test_normalize_requirements_handles_none_like_values(self):
        raw = "none N/A null"
        normalized = _normalize_requirements(raw)
        self.assertEqual(normalized, "")