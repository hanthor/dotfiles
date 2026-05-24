#!/bin/bash
set -e

KARNATAKA_IP="192.168.0.6"

echo "Fetching frontend pod name from karnataka..."
POD=$(ssh -o StrictHostKeyChecking=no core@$KARNATAKA_IP "sudo KUBECONFIG=/etc/kubernetes/admin.conf kubectl get pod -l app=frontend -n kubestellar -o jsonpath='{.items[0].metadata.name}'")
echo "Found frontend pod: $POD"

echo "Downloading index-BUr-cMfJ.js from pod to bihar..."
ssh -o StrictHostKeyChecking=no core@$KARNATAKA_IP "sudo KUBECONFIG=/etc/kubernetes/admin.conf kubectl exec deployment/frontend -n kubestellar -- cat /usr/share/nginx/html/assets/index-BUr-cMfJ.js" > /tmp/index-BUr-cMfJ.js

echo "Patching file on bihar using Python 3..."
python3 -c '
with open("/tmp/index-BUr-cMfJ.js", "r") as f:
    content = f.read()

# We look for the exact const Ss definition up to the return backtick
old_str = """const Ss=e=>{const t="",r=t.startsWith("https")?\"wss\":\"ws\",o=t.replace(/^https?:\\/\\//,\"\");return`"""
replacement = """const Ss=e=>{const t="",r=window.location.protocol===\"https:\"?\"wss\":\"ws\",o=window.location.host;return`"""

if old_str in content:
    content = content.replace(old_str, replacement)
    with open("/tmp/index-BUr-cMfJ.js", "w") as f:
        f.write(content)
    print("Successfully patched index-BUr-cMfJ.js on bihar")
else:
    # Try a regex-based or simpler match
    import re
    pattern = r"const Ss=e=>\{const t=\"\",r=t\.startsWith\(\"https\"\)\?\"wss\":\"ws\",o=t\.replace\(\/\^https\?:\\/\\/.*\,\"\"\);return`"
    new_content, count = re.subn(pattern, replacement, content)
    if count > 0:
        with open("/tmp/index-BUr-cMfJ.js", "w") as f:
            f.write(new_content)
        print(f"Successfully patched index-BUr-cMfJ.js via regex (replaced {count} occurrence)")
    else:
        print("ERROR: Pattern not found in index-BUr-cMfJ.js!")
        exit(1)
'

echo "Uploading patched file to karnataka..."
scp -o StrictHostKeyChecking=no /tmp/index-BUr-cMfJ.js core@$KARNATAKA_IP:/tmp/index-BUr-cMfJ.js

echo "Copying file into the frontend pod on karnataka..."
ssh -o StrictHostKeyChecking=no core@$KARNATAKA_IP "sudo KUBECONFIG=/etc/kubernetes/admin.conf kubectl cp /tmp/index-BUr-cMfJ.js kubestellar/$POD:/usr/share/nginx/html/assets/index-BUr-cMfJ.js && rm /tmp/index-BUr-cMfJ.js"

# Clean up locally
rm /tmp/index-BUr-cMfJ.js
echo "WebSocket patch completed successfully!"
