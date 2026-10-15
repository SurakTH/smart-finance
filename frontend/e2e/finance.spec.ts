import {signIn} from './auth';
import { test, expect } from "@playwright/test";
import path from "node:path";

test("login, dashboard, manually confirmed inbox, private chat and responsive layout", async ({
  page,
}, info) => {
  await signIn(page,true);
  await expect(page.getByRole("heading", { name: "การเงินของคุณ", exact: true })).toBeVisible();
  await expect(page.getByText("มูลค่าสุทธิ · ทุกบัญชี")).toBeVisible();
  await page.screenshot({
    path: path.join("..", "artifacts", `dashboard-${info.project.name}.png`),
    fullPage: true,
  });
  await expect
    .poll(() =>
      page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth + 1,
      ),
    )
    .toBe(true);
  if ((page.viewportSize()?.width || 1440) <= 900) {
    await page.getByRole("link",{name:"ทั้งหมด",exact:true}).click();
    await page.locator(".service-card").filter({has:page.getByRole("heading",{name:"AI Inbox",exact:true})}).click();
  } else await page
    .getByRole("link", { name: /AI Inbox/ })
    .first()
    .click();
  // Demo text deliberately uses a simple description without numeric IDs.
  await page
    .getByLabel("ข้อความรายการเงิน")
    .fill("รายการทดสอบเบราว์เซอร์ 12.50");
  await page.getByRole("button", { name: "สร้างข้อเสนอ", exact: true }).click();
  const row = page
    .locator(".proposal")
    .filter({ hasText: "รายการทดสอบเบราว์เซอร์" })
    .first();
  await expect(row).toBeVisible({ timeout: 20000 });
  await row.getByRole("button", { name: "ตรวจสอบ", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await dialog
    .getByLabel("บัญชีจ่ายเงิน")
    .selectOption({ label: "เงินสด · บัญชีเงิน" });
  await dialog
    .getByRole("combobox", { name: "หมวดหมู่", exact: true })
    .selectOption({ label: "อาหารและเครื่องดื่ม" });
  await dialog.getByRole("button", { name: "ยืนยันและบันทึก" }).click();
  await expect(page.getByText("บันทึกรายการเรียบร้อยแล้ว")).toBeVisible();
  await page.getByRole("link", { name: /^(รายการเงิน|รายการ)$/, exact: true }).click();
  await expect(
    page
      .locator(".transaction")
      .filter({ hasText: "รายการทดสอบเบราว์เซอร์" })
      .first(),
  ).toBeVisible();
  await page.getByRole("link", { name: /^(ผู้ช่วย AI|แชท AI)$/, exact: true }).click();
  await page.getByLabel("ข้อความถึง AI").fill("ยอดเงินเท่าไร");
  await page.getByRole("button", { name: "ส่งข้อความ", exact: true }).click();
  await expect(page.locator(".message.assistant").first()).toContainText(
    "รายงานจากระบบโดยตรง",
    { timeout: 20000 },
  );
  await expect
    .poll(() =>
      page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth + 1,
      ),
    )
    .toBe(true);
  // Attach, cancel, send without caption, then verify persistent receipt history.
  const receipt = {
    name: "receipt.png", mimeType: "image/png",
    buffer: Buffer.from("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", "base64"),
  };
  const input = page.getByLabel("แนบรูปสลิปในแชท");
  await input.setInputFiles(receipt);
  await expect(page.getByAltText("ตัวอย่างรูปก่อนส่ง")).toBeVisible();
  await page.getByRole("button", { name: "นำรูปออก", exact: true }).click();
  await expect(page.getByAltText("ตัวอย่างรูปก่อนส่ง")).toHaveCount(0);
  await input.setInputFiles(receipt);
  await page.getByRole("button", { name: "ส่งข้อความ", exact: true }).click();
  await expect(page.getByAltText("รูปที่แนบในบทสนทนา")).toBeVisible({ timeout: 20000 });
  await expect(page.locator(".message.assistant").last()).toContainText(/ยังไม่ได้บันทึก|ยังไม่มีการบันทึกยอดเงิน|ไม่ได้บันทึกยอดเงินเพิ่ม/, { timeout: 20000 });
  await expect(page.getByAltText("ตัวอย่างรูปก่อนส่ง")).toHaveCount(0);
  const image = page.getByAltText("รูปที่แนบในบทสนทนา");
  await expect.poll(() => image.evaluate((img: HTMLImageElement) => img.naturalWidth > 0)).toBe(true);
  const imageUrl = await image.getAttribute("src");
  const root = imageUrl!.split("/attachments/")[0];
  const rows = await (await page.request.get(root + "/transactions")).json();
  const selectedRoomIndex = await page.locator(".rooms button").evaluateAll((buttons) => buttons.findIndex((button) => button.classList.contains("selected")));
  await page.reload();
  if ((page.viewportSize()?.width || 1440) <= 900) await page.getByRole("button", { name: "เปิดประวัติการสนทนา", exact: true }).click();
  await page.locator(".rooms button").nth(selectedRoomIndex).click();
  await expect(page.getByAltText("รูปที่แนบในบทสนทนา")).toBeVisible();
  expect((await (await page.request.get(root + "/transactions")).json()).length).toBe(rows.length);
  await page.getByAltText("รูปที่แนบในบทสนทนา").scrollIntoViewIfNeeded();
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
  await page.screenshot({
    path: path.join("..", "artifacts", `chat-${info.project.name}.png`),
    fullPage: true,
  });
  await page.getByRole("link", { name: "กลับหน้าการเงิน", exact: true }).click();
  await page.getByRole("link", { name: "ตั้งค่า", exact: true }).first().click();
  await page
    .getByRole("button", { name: "ออกจากระบบ", exact: true })
    .filter({ visible: true })
    .first()
    .click();
  await expect(
    page.getByRole("button", { name: "เข้าสู่ระบบ", exact: true }),
  ).toBeVisible();
});
