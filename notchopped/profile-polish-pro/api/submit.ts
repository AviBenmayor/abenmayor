import type { VercelRequest, VercelResponse } from "@vercel/node";
import Airtable from "airtable";
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
    const base = new Airtable({ apiKey: process.env.AIRTABLE_API_KEY }).base(
      process.env.AIRTABLE_BASE_ID!
    );

    await base(process.env.AIRTABLE_TABLE_NAME!).create([
      {
        fields: {
          Name: name,
          Email: email,
          ...(age && { Age: age }),
          ...(apps && { "Dating Apps": apps }),
          ...(goals && { Goals: goals }),
          "Submitted At": new Date().toISOString(),
        },
      },
    ]);
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
