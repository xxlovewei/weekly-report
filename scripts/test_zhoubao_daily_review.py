import unittest
from collections import defaultdict
from datetime import date

from scripts.zhoubao_daily_review import finding


class ReviewFindingTests(unittest.TestCase):
    def review(self, content):
        commit = {"author": "tester", "sha": "abcd", "message": "修改请求处理"}
        comment = {"content": content, "category": "bug", "path": "src/handler.py"}
        return finding(1, date(2026, 11, 16), commit, comment, defaultdict(int))

    def test_reads_title_risk_and_suggestion_separately(self):
        issue = self.review("**问题标题：** 解析空请求时会抛异常\n风险说明：空请求导致服务报错。\n修改建议：先检查请求体。")
        self.assertEqual(issue["title"], "解析空请求时会抛异常")
        self.assertEqual(issue["risk"], "空请求导致服务报错。")
        self.assertEqual(issue["suggestion"], "先检查请求体。")

    def test_uses_a_complete_sentence_instead_of_cutting_a_long_description(self):
        detail = "错误分支一直重试。" + "请求队列持续积压，" * 40
        issue = self.review(f"问题描述：{detail}\n风险说明：流量高峰时会耗尽队列。\n修改建议：限制重试次数。")
        self.assertEqual(issue["title"], "错误分支一直重试。")
        self.assertIn(detail, issue["risk"])
        self.assertEqual(issue["suggestion"], "限制重试次数。")

    def test_falls_back_to_risk_when_title_has_no_short_sentence(self):
        issue = self.review(f"问题标题：{'长' * 151}\n风险说明：重复写入会产生重复数据。\n修改建议：按请求编号去重。")
        self.assertEqual(issue["title"], "重复写入会产生重复数据。")

    def test_uses_a_short_label_when_neither_field_has_a_complete_short_sentence(self):
        detail = "长" * 200
        issue = self.review(f"问题描述：{detail}\n风险说明：{detail}")
        self.assertLessEqual(len(issue["title"]), 150)
        self.assertIn("缺陷", issue["title"])
        self.assertEqual(issue["risk"], detail)


if __name__ == "__main__":
    unittest.main()
