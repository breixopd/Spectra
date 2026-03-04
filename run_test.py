import subprocess
res = subprocess.run(["python3", "-m", "pytest", "tests/e2e/test_plugin_management.py", "--tb=long"], capture_output=True, text=True)
print(res.stdout)
