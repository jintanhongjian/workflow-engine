# `send_email_skill`

*(Generated on 2026-03-06 12:04:24)*

**Import Path**: `from api_services.skills.email_send import send_email_skill`

发送邮件；支持纯文本、HTML 或 Markdown 正文.

### Parameters

| Parameter | Type | Description | Required |
| :--- | :--- | :--- | :--- |
| `subject` | *string* | Parameter subject | ✅ Yes |
| `body` | *string* | Parameter body | ✅ Yes |
| `recipients` | *string* | Parameter recipients | ✅ Yes |
| `attachments` | *string* | Parameter attachments | No |
| `is_html` | *boolean* | Parameter is_html | No |