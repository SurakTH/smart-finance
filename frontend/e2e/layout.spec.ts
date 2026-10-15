import {signIn} from './auth';
import { test, expect } from "@playwright/test";

test("finance navigation and a dedicated full-height AI chat", async ({ page }, info) => {
  await signIn(page);
  await expect(page.getByRole("heading", { name: "การเงินของคุณ", exact: true })).toBeVisible();
  const compact = (page.viewportSize()?.width || 1440) <= 900;
  if (compact) {
    await expect(page.getByRole("navigation", { name: "เมนูหลักบนมือถือ" })).toBeVisible();
    await expect(page.locator(".sidebar")).toBeHidden();
  }
  if (!compact) {
    const services=page.locator('.sidebar-bottom').getByRole('link',{name:'บริการทั้งหมด',exact:true});
    await expect(services).toBeInViewport();
    const before=await services.boundingBox();
    await page.locator('.sidebar nav').evaluate(node=>{node.scrollTop=node.scrollHeight;});
    await expect(services).toBeInViewport();
    expect((await services.boundingBox())!.y).toBe(before!.y);
  }
  await page.getByRole("link", { name: /^(ผู้ช่วย AI|แชท AI)$/ }).click();
  await expect(page.getByRole("heading", { name: /วันนี้ อยากคุย/ })).toBeVisible();
  await expect(page.locator(".page-heading")).toHaveCount(0);
  await expect(page.locator(".bottom-nav")).toHaveCount(0);
  await expect(page.getByLabel("ข้อความถึง AI")).toBeInViewport();
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollHeight <= innerHeight + 1)).toBe(true);
  await page.getByRole("button", { name: "ตอนนี้ฉันมีเงินเท่าไร?", exact: false }).click();
  await expect(page.getByLabel("ข้อความถึง AI")).toHaveValue("ตอนนี้ฉันมีเงินเท่าไร?");
  await page.getByLabel("ข้อความถึง AI").fill("");
  await page.screenshot({ path: `../artifacts/assistant-new-${info.project.name}.png`, fullPage: true });
  const toggle = page.getByRole("button", { name: "เปิดประวัติการสนทนา", exact: true });
  if (!compact) await toggle.click();
  await expect(page.locator(".chat-history")).toBeHidden();
  await toggle.click();
  await expect(page.locator(".chat-history")).toBeVisible();
  if (compact) {
    await expect(page.getByRole("dialog", { name: "ประวัติการสนทนา" })).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.locator(".chat-history")).toBeHidden();
    await expect(toggle).toBeFocused();
  }
  await page.setViewportSize({ width: compact ? 360 : 1000, height: 560 });
  await expect(page.getByLabel("ข้อความถึง AI")).toBeInViewport();
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
  await expect.poll(() => page.evaluate(() => {
    const composer = document.querySelector(".composer")!.getBoundingClientRect();
    return composer.bottom <= (visualViewport?.height || innerHeight) && composer.top >= 0;
  })).toBe(true);
});
