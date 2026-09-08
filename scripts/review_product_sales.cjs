// Two synthetic customer turns. Does not approve, send, or sync drafts.
const { chromium } = require(process.env.PLAYWRIGHT_PATH || 'playwright');
const assert = require('node:assert/strict');
(async () => {
  const browser = await chromium.launch({ headless: true, channel: 'chrome' });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(process.env.REVIEW_URL || 'http://127.0.0.1:8011/?review=product-sales');
    await page.locator('#workspaceMode').filter({ hasText: process.env.REVIEW_PUBLIC_DEMO === 'true' ? /Demo|演示/i : 'Operator' }).waitFor();
    await page.selectOption('#conversationChannel', 'web_chat');
    await page.fill('#conversationSenderName', '产品推荐验证');
    async function send(message) {
      await page.fill('#conversationMessage', message);
      const responsePromise = page.waitForResponse(response => response.url().endsWith('/conversations/messages') && response.request().method() === 'POST', { timeout: 90000 });
      await page.click('#conversationSend');
      const response = await responsePromise;
      assert.equal(response.status(), 200);
      const data = await response.json();
      await page.locator('#conversationProducts').waitFor({ state: 'visible' });
      assert.equal(data.reply_draft.recommended_products[0].product_name, 'Yunnan Family Tour');
      assert.ok((await page.inputValue('#conversationDraft')).includes('云南家庭游'));
      assert.ok((await page.textContent('#conversationProducts')).includes('7天6晚'));
      return data;
    }
    const first = await send('我们4个人想去云南，一共7天，有什么对应产品？');
    const second = await send('酒店选择四星，需要包车，导游语言中文。');
    assert.equal(second.turn_number, 2);
    assert.deepEqual(second.open_questions, []);
    assert.ok((await page.textContent('#conversationFacts')).includes('4星级'));
    const result = { first: first.llm_trace, second: second.llm_trace, second_method: second.reply_draft.generation_method, product: second.reply_draft.recommended_products[0].product_name };
    if (process.env.REQUIRE_LIVE_LLM === 'true') {
      assert.equal(second.llm_trace.understanding, 'succeeded');
      assert.equal(second.llm_trace.generation, 'succeeded');
    }
    await page.locator('#conversationProducts').screenshot({ path: '../tmp/product-sales-desktop.png' });
    if (process.env.REVIEW_SCREENSHOT) {
      await page.locator('#conversationProducts').scrollIntoViewIfNeeded();
      await page.screenshot({ path: process.env.REVIEW_SCREENSHOT });
    }
    await page.click('#languageToggle');
    assert.ok((await page.textContent('#conversationProducts')).includes('Recommended product'));
    await page.click('#languageToggle');
    await page.setViewportSize({ width: 390, height: 844 });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true);
    await page.locator('#conversationProducts').screenshot({ path: '../tmp/product-sales-mobile.png' });
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({ status: 'PASS', ...result }));
  } finally { await browser.close(); }
})().catch(error => { console.error(error.message); process.exit(1); });
