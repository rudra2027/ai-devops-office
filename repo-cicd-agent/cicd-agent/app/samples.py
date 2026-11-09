"""Sample changes so the pipeline can be tried without a repository."""

SAMPLES = [
    {
        "id": "clean-refactor", "label": "Tidy refactor", "blurb": "Extracts a helper and adds a unit test. Should be low risk.",
        "title": "Extract price formatting helper",
        "diff": """diff --git a/shop/pricing.py b/shop/pricing.py
--- a/shop/pricing.py
+++ b/shop/pricing.py
@@ -1,9 +1,14 @@
+def format_price(cents: int, currency: str = "EUR") -> str:
+    \"\"\"Formats an integer amount of cents, e.g. 1999 -> '19.99 EUR'.\"\"\"
+    return f"{cents / 100:.2f} {currency}"
+
+
 def cart_total(items):
     total = 0
     for item in items:
         total += item["cents"] * item["qty"]
-    return "%.2f EUR" % (total / 100)
+    return format_price(total)
diff --git a/tests/test_pricing.py b/tests/test_pricing.py
--- /dev/null
+++ b/tests/test_pricing.py
@@ -0,0 +1,6 @@
+from shop.pricing import format_price, cart_total
+
+
+def test_format_price():
+    assert format_price(1999) == "19.99 EUR"
+    assert cart_total([{"cents": 500, "qty": 2}]) == "10.00 EUR"
""",
    },
    {
        "id": "sql-injection", "label": "Risky query", "blurb": "Builds SQL with string concatenation. The reviewer should flag injection.",
        "title": "Add user lookup endpoint",
        "diff": """diff --git a/api/users.py b/api/users.py
--- a/api/users.py
+++ b/api/users.py
@@ -10,3 +10,9 @@ def get_user(user_id):
     return db.query("SELECT * FROM users WHERE id = %s", (user_id,))
+
+
+def find_by_name(name):
+    # quick search used by the admin page
+    sql = "SELECT * FROM users WHERE name = '" + name + "'"
+    return db.execute(sql)
""",
    },
    {
        "id": "secret-leak", "label": "Leaked secret", "blurb": "Commits a credential. The secret scan blocks this and approval cannot override it.",
        "title": "Wire up S3 uploads",
        "diff": """diff --git a/config/storage.py b/config/storage.py
--- a/config/storage.py
+++ b/config/storage.py
@@ -1,4 +1,8 @@
 import boto3
+
+AWS_ACCESS_KEY_ID = "AKIAIOSFODNN7EXAMPLE"
+AWS_SECRET_ACCESS_KEY = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"

-client = boto3.client("s3")
+client = boto3.client("s3", aws_access_key_id=AWS_ACCESS_KEY_ID, aws_secret_access_key=AWS_SECRET_ACCESS_KEY)
""",
    },
]
BY_ID = {s["id"]: s for s in SAMPLES}
