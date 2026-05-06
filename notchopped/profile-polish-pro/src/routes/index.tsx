import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { z } from "zod";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { toast } from "sonner";
import { Toaster } from "@/components/ui/sonner";


export const Route = createFileRoute("/")({
  component: Index,
  head: () => ({
    meta: [
      { title: "NotChopped — Dating Profile Revamp for Men" },
      {
        name: "description",
        content:
          "Get more matches. Premium dating profile revamp service for men — photos, bio, and strategy that convert.",
      },
      { property: "og:title", content: "NotChopped — Dating Profile Revamp for Men" },
      {
        property: "og:description",
        content: "Premium dating profile revamp for men. More matches, better dates.",
      },
    ],
  }),
});

const schema = z.object({
  name: z.string().trim().min(1, "Name is required").max(80),
  email: z.string().trim().email("Invalid email").max(160),
  age: z.string().trim().regex(/^\d{2,3}$/, "Enter a valid age").optional().or(z.literal("")),
  apps: z.string().optional(),
  goals: z.string().trim().max(800).optional().or(z.literal("")),
});

function Index() {
  const [submitting, setSubmitting] = useState(false);
  const [selectedApps, setSelectedApps] = useState<string[]>([]);
  const [otherApp, setOtherApp] = useState("");

  const toggleApp = (app: string) =>
    setSelectedApps((prev) =>
      prev.includes(app) ? prev.filter((a) => a !== app) : [...prev, app]
    );

  const DATING_APPS = ["Hinge", "Bumble", "Tinder", "Raya"];

  const onSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const fd = new FormData(e.currentTarget);
    const parsed = schema.safeParse({
      ...Object.fromEntries(fd),
      apps: [...selectedApps, ...(otherApp.trim() ? [`Other: ${otherApp.trim()}`] : [])].join(", ") || undefined,
    });
    if (!parsed.success) {
      toast.error(parsed.error.issues[0]?.message ?? "Please check the form");
      return;
    }
    setSubmitting(true);
    try {
      const res = await fetch("/api/submit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(parsed.data),
      });
      if (!res.ok) throw new Error("Server error");
      (e.target as HTMLFormElement).reset();
      setSelectedApps([]);
      setOtherApp("");
      toast.success("You're in. We'll reach out within 24 hours.");
    } catch {
      toast.error("Something went wrong. Please try again.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen bg-background text-foreground">
      <Toaster theme="dark" />

      {/* Nav */}
      <header className="absolute top-0 z-20 w-full px-6 py-6 md:px-12">
        <div className="mx-auto flex max-w-7xl items-center justify-between">
          <div className="text-lg font-semibold tracking-tight">
            Not<span className="text-primary">Chopped</span>
          </div>
          <a
            href="#apply"
            className="text-sm font-medium text-muted-foreground transition-colors hover:text-foreground"
          >
            Apply →
          </a>
        </div>
      </header>

      {/* Hero */}
      <section
        className="relative overflow-hidden"
        style={{ background: "var(--gradient-hero)" }}
      >
        <div className="mx-auto max-w-3xl px-6 pb-20 pt-32 text-center md:px-12 md:pb-28 md:pt-40">
          <span className="mb-6 inline-flex items-center gap-2 rounded-full border border-border bg-card/40 px-4 py-1.5 text-xs font-medium text-muted-foreground backdrop-blur">
            <span className="h-1.5 w-1.5 rounded-full bg-primary" />
            Now accepting applications
          </span>
          <h1 className="text-4xl font-bold leading-[1.05] tracking-tight md:text-6xl lg:text-7xl">
            Stop swiping.
            <br />
            <span
              className="bg-clip-text text-transparent"
              style={{ backgroundImage: "var(--gradient-gold)" }}
            >
              Start matching.
            </span>
          </h1>
          <p className="mx-auto mt-6 max-w-xl text-lg text-muted-foreground md:text-xl">
            We revamp dating profiles for men who are tired of being invisible. Better photos.
            Sharper bio. A strategy that actually converts.
          </p>
          <a
            href="#apply"
            className="mt-10 inline-flex items-center justify-center rounded-full px-8 py-4 text-sm font-semibold text-primary-foreground transition-transform hover:scale-[1.02]"
            style={{ background: "var(--gradient-gold)", boxShadow: "var(--shadow-glow)" }}
          >
            Apply for a revamp
          </a>
        </div>
      </section>

      {/* What's included */}
      <section className="border-t border-border bg-card/20 px-6 py-20 md:px-12 md:py-28">
        <div className="mx-auto max-w-7xl">
          <h2 className="max-w-2xl text-3xl font-bold tracking-tight md:text-5xl">
            Everything you need, dialed in.
          </h2>
          <div className="mt-12 grid grid-cols-1 gap-6 md:grid-cols-3">
            <Feature
              title="Photo audit"
              body="We rank your current photos and tell you exactly which ones to keep, cut, or reshoot."
            />
            <Feature
              title="Bio rewrite"
              body="A scroll-stopping bio written in your voice — designed to start conversations, not end them."
            />
            <Feature
              title="App strategy"
              body="Hinge, Bumble, Tinder — we tune your profile and prompts for the platform you actually use."
            />
          </div>
        </div>
      </section>

      {/* Form */}
      <section id="apply" className="px-6 py-20 md:px-12 md:py-28">
        <div className="mx-auto max-w-2xl">
          <div className="text-center">
            <h2 className="text-3xl font-bold tracking-tight md:text-5xl">Apply for a revamp</h2>
            <p className="mt-4 text-muted-foreground">
              Tell us a bit about yourself. We'll be in touch within 24 hours.
            </p>
          </div>

          <form
            onSubmit={onSubmit}
            className="mt-12 space-y-5 rounded-2xl border border-border bg-card p-6 md:p-10"
            style={{ boxShadow: "var(--shadow-elegant)" }}
          >
            <Field label="Full name" name="name" placeholder="Alex Carter" required />
            <Field
              label="Email"
              name="email"
              type="email"
              placeholder="alex@example.com"
              required
            />
            <Field label="Age" name="age" placeholder="32" />
            <div>
              <Label className="text-sm font-medium">Apps you use</Label>
              <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-5">
                {DATING_APPS.map((app) => (
                  <label
                    key={app}
                    className="flex cursor-pointer items-center gap-2 rounded-md border border-border px-3 py-2 text-sm transition-colors hover:bg-accent has-[[data-state=checked]]:border-primary has-[[data-state=checked]]:bg-primary/10"
                  >
                    <Checkbox
                      checked={selectedApps.includes(app)}
                      onCheckedChange={() => toggleApp(app)}
                    />
                    {app}
                  </label>
                ))}
                <label className="flex cursor-pointer items-center gap-2 rounded-md border border-border px-3 py-2 text-sm transition-colors hover:bg-accent has-[[data-state=checked]]:border-primary has-[[data-state=checked]]:bg-primary/10">
                  <Checkbox
                    checked={selectedApps.includes("Other")}
                    onCheckedChange={() => toggleApp("Other")}
                  />
                  Other
                </label>
              </div>
              {selectedApps.includes("Other") && (
                <Input
                  className="mt-2 bg-background"
                  placeholder="Which app?"
                  value={otherApp}
                  onChange={(e) => setOtherApp(e.target.value)}
                />
              )}
            </div>
            <div>
              <Label htmlFor="goals" className="text-sm font-medium">
                What do you want to change?
              </Label>
              <Textarea
                id="goals"
                name="goals"
                rows={4}
                maxLength={800}
                placeholder="Few matches, not sure what's wrong with my photos, want better quality dates…"
                className="mt-2 resize-none bg-background"
              />
            </div>

            <Button
              type="submit"
              disabled={submitting}
              className="h-12 w-full rounded-full text-base font-semibold text-primary-foreground hover:opacity-90"
              style={{ background: "var(--gradient-gold)", boxShadow: "var(--shadow-glow)" }}
            >
              {submitting ? "Sending…" : "Submit application"}
            </Button>
            <p className="text-center text-xs text-muted-foreground">
              No spam. Your info stays private.
            </p>
          </form>
        </div>
      </section>

      <footer className="border-t border-border px-6 py-8 text-center text-sm text-muted-foreground md:px-12">
        © {new Date().getFullYear()} NotChopped. All rights reserved.
      </footer>
    </div>
  );
}

function Stat({ n, label }: { n: string; label: string }) {
  return (
    <div>
      <div className="text-2xl font-bold text-foreground">{n}</div>
      <div className="text-xs uppercase tracking-wider">{label}</div>
    </div>
  );
}

function Feature({ title, body }: { title: string; body: string }) {
  return (
    <div className="rounded-2xl border border-border bg-card p-6 transition-colors hover:border-primary/50">
      <div
        className="mb-4 h-10 w-10 rounded-lg"
        style={{ background: "var(--gradient-gold)" }}
      />
      <h3 className="text-lg font-semibold">{title}</h3>
      <p className="mt-2 text-sm text-muted-foreground">{body}</p>
    </div>
  );
}

function Field({
  label,
  name,
  type = "text",
  placeholder,
  required,
}: {
  label: string;
  name: string;
  type?: string;
  placeholder?: string;
  required?: boolean;
}) {
  return (
    <div>
      <Label htmlFor={name} className="text-sm font-medium">
        {label}
        {required && <span className="ml-1 text-primary">*</span>}
      </Label>
      <Input
        id={name}
        name={name}
        type={type}
        placeholder={placeholder}
        required={required}
        className="mt-2 h-11 bg-background"
      />
    </div>
  );
}
