# Agent Guidelines for skills-akaihola

## Critical: Personal Information Protection

**ABSOLUTE REQUIREMENT**: Never include PII (names, emails, addresses, company names) or actual message content in public-facing materials.

### What to Obfuscate

- Real names and email addresses
- Company/organization names identifying individuals
- Phone numbers, physical addresses, account numbers
- Actual email message bodies or subjects
- Financial information, proprietary content

### Obfuscation Examples

| ❌ INCORRECT                          | ✅ CORRECT                                |
| ------------------------------------- | ----------------------------------------- |
| `"Message from user@company.example"` | `"Message from unknown sender"`           |
| `"Subject: Financial Report Q4"`      | `"Subject: business-related subject"`     |
| `"Organization Name sent data"`       | `"Unknown sender sent a business report"` |
| `test_email_from_user_name()`         | `test_email_from_unknown_sender()`        |
| `{"from": "user@company.example"}`    | `{"from": "sender@company.example"}`      |

### Guidelines

1. Use `@example.com` or `@example.org` in all test data (RFC 2606 reserved)
2. Use generic descriptors: "unknown sender", "business matter", "financial document"
3. Use message IDs when referencing specific messages (e.g., "Message 57039")
4. Document the problem, not the message content
5. Always run `git diff` before committing to verify no PII

### Pre-Commit Checklist

- [ ] No real names in code or tests
- [ ] No real email addresses in code or tests
- [ ] No company names identifying individuals
- [ ] Test data uses example domains only
- [ ] Issue/PR descriptions are generic
- [ ] No actual message content in documentation
