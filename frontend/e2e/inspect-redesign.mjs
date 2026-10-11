import { chromium } from 'playwright';
import fs from 'node:fs';
const credentials=JSON.parse(fs.readFileSync(process.env.SF_DEMO_CREDENTIALS || '../artifacts/demo-access.json','utf8'));
const baseURL=process.env.SF_BASE_URL || 'http://localhost:8080';
const browser=await chromium.launch(process.env.SF_CHROME_PATH ? {executablePath:process.env.SF_CHROME_PATH} : {});
const page=await browser.newPage({viewport:{width:1440,height:1000}});
await page.goto(baseURL);
await page.getByLabel('อีเมล',{exact:true}).fill(credentials.email);
await page.getByLabel('รหัสผ่าน',{exact:true}).fill(credentials.password);
await page.getByRole('button',{name:'เข้าสู่ระบบ',exact:true}).click();
await page.locator('.page-heading').waitFor();
for (const width of [1440,393,360]) {
 await page.setViewportSize({width,height:width>900?1000:852});
 for (const route of ['','transactions','accounts','categories','budgets','goals','recurring','members','workspaces','join','register','services','inbox','assistant','settings']) {
  await page.goto(baseURL+'/'+route);
  await page.locator(route==='assistant'?'.chat-topbar':(route==='join'||route==='register')?'.join-card':'.page-heading').waitFor();
  if (!route) await page.locator('.overview-hero').waitFor();
  if (route==='transactions') await page.locator('.transaction').first().waitFor();
  if (route==='budgets') await page.locator('.budget-overview').waitFor();
  if (route==='goals') await page.locator('.goals-overview').waitFor();
  if (route==='workspaces') await page.locator('.workspace-card').first().waitFor();
  if (route==='members') await page.locator('.member-row').first().waitFor();
  if (route==='recurring') await page.locator('.recurring-overview').waitFor();
  if (route==='services') await page.locator('.services-intro').waitFor();
  if (route==='categories') await page.locator('.category-directory').waitFor();
  if (route==='accounts') await page.locator('.account').first().waitFor();
  await page.evaluate(()=>document.fonts.ready);
  const metrics=await page.evaluate(()=>({overflow:document.documentElement.scrollWidth>innerWidth+1,height:document.documentElement.scrollHeight,viewport:innerHeight,composer:document.querySelector('.composer')?.getBoundingClientRect().bottom}));
  console.log(JSON.stringify({width,route:route||'dashboard',...metrics}));
  await page.screenshot({path:`../artifacts/redesign-${route||'dashboard'}-${width}.png`,fullPage:route!=='workspaces'});
 }
}
await browser.close();
