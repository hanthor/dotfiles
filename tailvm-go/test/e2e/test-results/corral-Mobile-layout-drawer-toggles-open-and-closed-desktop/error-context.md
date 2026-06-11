# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: corral.spec.js >> Mobile layout >> drawer toggles open and closed
- Location: corral.spec.js:124:3

# Error details

```
Error: expect(locator).toBeVisible() failed

Locator:  locator('#btn-menu')
Expected: visible
Received: hidden

Call log:
  - Expect "toBeVisible" with timeout 10000ms
  - waiting for locator('#btn-menu')
    23 × locator resolved to <button id="btn-menu" class="icon-btn" aria-label="Menu">…</button>
       - unexpected value "hidden"

```

```yaml
- banner:
  - text: 🤠
  - strong: Corral
  - text: Virtual Environment
  - button "Create VM"
- complementary: Datacenter Extensions bihar control-plane boot-test default karnataka bluefin-test-df1f56ef-7112-45d8-ad1a-9bbef01b20a0 bluefin-test test-fleet-fedora default test-fleet-node2 default alpine-pet-hd default
- main:
  - heading "Datacenter" [level=1]
  - text: 5 virtual machines 3 running 2/2 nodes ready
  - table:
    - rowgroup:
      - row "Name Status Node Namespace CPU Mem IP":
        - columnheader "Name"
        - columnheader "Status"
        - columnheader "Node"
        - columnheader "Namespace"
        - columnheader "CPU"
        - columnheader "Mem"
        - columnheader "IP"
    - rowgroup:
      - row "bluefin-test-df1f56ef-7112-45d8-ad1a-9bbef01b20a0 ○ CrashLoopBackOff karnataka bluefin-test 4 8Gi —":
        - cell "bluefin-test-df1f56ef-7112-45d8-ad1a-9bbef01b20a0"
        - cell "○ CrashLoopBackOff"
        - cell "karnataka"
        - cell "bluefin-test"
        - cell "4"
        - cell "8Gi"
        - cell "—"
      - row "alpine-pet-hd ○ Stopped — default 4 8Gi —":
        - cell "alpine-pet-hd"
        - cell "○ Stopped"
        - cell "—"
        - cell "default"
        - cell "4"
        - cell "8Gi"
        - cell "—"
      - row "boot-test ● Running bihar default 2 4Gi 10.244.0.58":
        - cell "boot-test"
        - cell "● Running"
        - cell "bihar"
        - cell "default"
        - cell "2"
        - cell "4Gi"
        - cell "10.244.0.58"
      - row "test-fleet-fedora ● Running karnataka default 2 2Gi 10.244.1.225":
        - cell "test-fleet-fedora"
        - cell "● Running"
        - cell "karnataka"
        - cell "default"
        - cell "2"
        - cell "2Gi"
        - cell "10.244.1.225"
      - row "test-fleet-node2 ● Running karnataka default 2 2Gi 10.244.1.226":
        - cell "test-fleet-node2"
        - cell "● Running"
        - cell "karnataka"
        - cell "default"
        - cell "2"
        - cell "2Gi"
        - cell "10.244.1.226"
  - heading "Image library Import image" [level=2]:
    - text: Image library
    - button "Import image"
  - table:
    - rowgroup:
      - row "Name Namespace Size Status Source":
        - columnheader "Name"
        - columnheader "Namespace"
        - columnheader "Size"
        - columnheader "Status"
        - columnheader "Source"
        - columnheader
    - rowgroup:
      - row "boot-test-rootdisk default 25Gi Succeeded https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img":
        - cell "boot-test-rootdisk"
        - cell "default"
        - cell "25Gi"
        - cell "Succeeded"
        - cell "https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img"
        - cell:
          - button
```

```
Error: write EPIPE
```

# Test source

```ts
  27  |     const hasMsg = (await page.locator('.console-msg').count()) > 0;
  28  |     expect(hasTable || hasMsg).toBeTruthy();
  29  |   });
  30  | 
  31  |   test('image library section exists', async ({ page }) => {
  32  |     await expect(page.locator('h2.section')).toContainText('Image library');
  33  |     await expect(page.locator('#dc-images')).toBeVisible();
  34  |   });
  35  | 
  36  |   test('header shows brand and create button', async ({ page }) => {
  37  |     await expect(page.locator('.brand')).toContainText('Corral');
  38  |     await expect(page.locator('#btn-create')).toBeVisible();
  39  |   });
  40  | });
  41  | 
  42  | test.describe('Create dialog', () => {
  43  |   test.beforeEach(async ({ page }) => {
  44  |     await page.goto('/');
  45  |     await waitForPageLoad(page);
  46  |   });
  47  | 
  48  |   test('opens and closes', async ({ page }) => {
  49  |     await openCreateDialog(page);
  50  |     await expect(page.locator('#create-dialog h2')).toContainText('Create');
  51  |     await closeCreateDialog(page);
  52  |     await expect(page.locator('#create-dialog')).not.toBeVisible();
  53  |   });
  54  | 
  55  |   test('has source type selector', async ({ page }) => {
  56  |     await openCreateDialog(page);
  57  |     await expect(page.locator('[name=sourceType]')).toBeVisible();
  58  |     const count = await page.locator('[name=sourceType] option').count();
  59  |     expect(count).toBeGreaterThanOrEqual(3);
  60  |     await closeCreateDialog(page);
  61  |   });
  62  | 
  63  |   test('bootc source shows SSH key field', async ({ page }) => {
  64  |     await openCreateDialog(page);
  65  |     const bootcOpt = page.locator('[name=sourceType] option[value=bootc]');
  66  |     if (await bootcOpt.count() === 0) { await closeCreateDialog(page); return; }
  67  |     await page.selectOption('[name=sourceType]', 'bootc');
  68  |     await expect(page.locator('#sshkey-field')).toBeVisible();
  69  |     await closeCreateDialog(page);
  70  |   });
  71  | 
  72  |   test('required source types are present', async ({ page }) => {
  73  |     await openCreateDialog(page);
  74  |     const values = await page.locator('[name=sourceType] option').evaluateAll(
  75  |       (els) => els.map((e) => e.value)
  76  |     );
  77  |     expect(values).toContain('containerDisk');
  78  |     expect(values).toContain('iso');
  79  |     expect(values).toContain('pvc');
  80  |     await closeCreateDialog(page);
  81  |   });
  82  | 
  83  |   test('name field is present and required', async ({ page }) => {
  84  |     await openCreateDialog(page);
  85  |     const nameInput = page.locator('[name=name]');
  86  |     await expect(nameInput).toBeVisible();
  87  |     expect(await nameInput.getAttribute('required')).not.toBeNull();
  88  |     await closeCreateDialog(page);
  89  |   });
  90  | });
  91  | 
  92  | test.describe('Tree navigation', () => {
  93  |   test.beforeEach(async ({ page }) => {
  94  |     await page.goto('/');
  95  |     await waitForPageLoad(page);
  96  |   });
  97  | 
  98  |   test('clicking a node shows node detail view', async ({ page }) => {
  99  |     const nodeItems = page.locator('.tree-item.lvl-1');
  100 |     if (await nodeItems.count() === 0) return; // no nodes
  101 |     await nodeItems.first().click();
  102 |     await page.waitForTimeout(500);
  103 |     expect(await page.locator('.page-head h1').textContent()).toBeTruthy();
  104 |   });
  105 | });
  106 | 
  107 | test.describe('Extensions page', () => {
  108 |   test.beforeEach(async ({ page }) => {
  109 |     await page.goto('/');
  110 |     await waitForPageLoad(page);
  111 |   });
  112 | 
  113 |   test('navigating to Extensions shows plugin list', async ({ page }) => {
  114 |     // The Extensions tree item may not exist in older deployments
  115 |     const extItem = page.locator('.tree-item', { hasText: 'Extension' });
  116 |     if (await extItem.count() === 0) return;
  117 |     await extItem.first().click();
  118 |     await page.waitForTimeout(500);
  119 |     await expect(page.locator('.page-head h1')).toContainText('Extension');
  120 |   });
  121 | });
  122 | 
  123 | test.describe('Mobile layout', () => {
  124 |   test('drawer toggles open and closed', async ({ page }) => {
  125 |     await page.goto('/');
  126 |     await waitForPageLoad(page);
> 127 |     await expect(page.locator('#btn-menu')).toBeVisible();
      |     ^ Error: write EPIPE
  128 |     const tree = page.locator('#tree');
  129 |     await expect(tree).not.toHaveClass(/open/);
  130 |     await page.locator('#btn-menu').click();
  131 |     await page.waitForTimeout(300);
  132 |     await expect(tree).toHaveClass(/open/);
  133 |     await page.locator('#btn-menu').click();
  134 |     await page.waitForTimeout(300);
  135 |     await expect(tree).not.toHaveClass(/open/);
  136 |   });
  137 | 
  138 |   test('create VM button works on mobile', async ({ page }) => {
  139 |     await page.goto('/');
  140 |     await waitForPageLoad(page);
  141 |     await openCreateDialog(page);
  142 |     await expect(page.locator('#create-dialog h2')).toContainText('Create');
  143 |     await closeCreateDialog(page);
  144 |   });
  145 | });
  146 | 
```