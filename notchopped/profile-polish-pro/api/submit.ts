import type { VercelRequest, VercelResponse } from "@vercel/node";
import twilio from "twilio";

export default async function handler(req: VercelRequest, res: VercelResponse) {
  if (req.method !== "POST") {
    return res.status(405).json({ error: "Method not allowed" });
  }

  const { name, email, age, apps, goals } = req.body as {
    name: string;
    email: string;
    age?: string;
    apps?: string;
    goals?: string;
  };

  if (!name || !email) {
    return res.status(400).json({ error: "Name and email are required" });
  }

  try {
    const url = `https://api.airtable.com/v0/${process.env.AIRTABLE_BASE_ID}/${encodeURIComponent(process.env.AIRTABLE_TABLE_NAME!)}`;
    const airtableRes = await fetch(url, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${process.env.AIRTABLE_API_KEY}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        records: [
          {
            fields: {
              Name: name,
              Email: email,
              ...(age && { Age: Number(age) }),
              ...(apps && { "Dating Apps": apps }),
              ...(goals && { Goals: goals }),
              "Submitted At": new Date().toISOString(),
            },
          },
        ],
      }),
    });

    if (!airtableRes.ok) {
      const detail = await airtableRes.json();
      console.error("Airtable error:", JSON.stringify(detail));
      return res.status(500).json({ error: "Failed to save submission" });
    }
  } catch (err) {
    console.error("Airtable error:", err);
    return res.status(500).json({ error: "Failed to save submission" });
  }

  try {
    const client = twilio(
      process.env.TWILIO_ACCOUNT_SID,
      process.env.TWILIO_AUTH_TOKEN
    );

    const recipients = (process.env.TWILIO_WHATSAPP_TO ?? "").split(",").filter(Boolean);
    const from = `whatsapp:${process.env.TWILIO_WHATSAPP_FROM}`;
    const body =
      `📋 *New NotChopped Application*\n\n` +
      `*Name:* ${name}\n` +
      `*Email:* ${email}\n` +
      (age ? `*Age:* ${age}\n` : "") +
      (apps ? `*Dating Apps:* ${apps}\n` : "") +
      (goals ? `*Goals:* ${goals}` : "");

    await Promise.all(
      recipients.map((number) =>
        client.messages.create({ from, to: `whatsapp:${number.trim()}`, body })
      )
    );
  } catch (err) {
    console.error("Twilio error:", err);
    // Don't fail the request if WhatsApp alert fails — submission is already saved
  }

  return res.status(200).json({ success: true });
}
