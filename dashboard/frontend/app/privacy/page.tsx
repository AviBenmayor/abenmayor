export default function PrivacyPolicy() {
    return (
        <main className="min-h-screen bg-white text-black p-8 md:p-12 max-w-4xl mx-auto font-sans">
            <h1 className="text-4xl font-bold mb-6">Privacy Policy for Personal Data Dashboard</h1>
            <p className="mb-4 text-sm text-zinc-500">Last Updated: December 26, 2025</p>

            <section className="mb-8">
                <h2 className="text-2xl font-semibold mb-4">1. Introduction</h2>
                <p className="leading-7">
                    This Personal Data Dashboard is a <strong>self-hosted</strong>, <strong>local-first</strong> application designed to aggregate your personal financial and health data. This policy explains how your data is handled.
                </p>
            </section>

            <section className="mb-8">
                <h2 className="text-2xl font-semibold mb-4">2. Data Collection & Storage</h2>
                <h3 className="text-xl font-medium mb-2">Local Storage</h3>
                <ul className="list-disc pl-6 mb-4 space-y-2">
                    <li>All data aggregated by this dashboard resides <strong>strictly on your local machine</strong>.</li>
                    <li>This application <strong>does not</strong> transmit your data to any external server controlled by the dashboard developers.</li>
                    <li>You are the sole custodian of your data.</li>
                </ul>

                <h3 className="text-xl font-medium mb-2">Third-Party Connections</h3>
                <p className="leading-7 mb-2">This dashboard connects directly to the following third-party services using your credentials:</p>
                <ul className="list-disc pl-6 space-y-2">
                    <li><strong>Plaid (Banking)</strong>: Connects via Plaid API. Your banking credentials are not stored by this application; connection is maintained via access tokens stored locally.</li>
                    <li><strong>Whoop</strong>: Connects via Whoop API using your personal developer credentials.</li>
                    <li><strong>Fidelity</strong>: Parses CSV files provided by you. No direct connection.</li>
                    <li><strong>Apple Health</strong>: Parses XML exports provided by you. No direct connection.</li>
                </ul>
            </section>

            <section className="mb-8">
                <h2 className="text-2xl font-semibold mb-4">3. Data Usage</h2>
                <ul className="list-disc pl-6 space-y-2">
                    <li>Data is used solely for <strong>visualization</strong> within the dashboard.</li>
                    <li>No data is sold, analyzed, or shared with third parties by this application.</li>
                </ul>
            </section>

            <section className="mb-8">
                <h2 className="text-2xl font-semibold mb-4">4. Security</h2>
                <ul className="list-disc pl-6 space-y-2">
                    <li><strong>API Keys</strong>: You are responsible for keeping your API keys secure. We recommend storing them in environment variables or a <code>.env</code> file that is not checked into version control.</li>
                    <li><strong>Local Access</strong>: Since the dashboard runs locally (<code>localhost</code>), ensure your machine is free of malware to prevent data scraping.</li>
                </ul>
            </section>

            <section className="mb-8">
                <h2 className="text-2xl font-semibold mb-4">5. Changes to This Policy</h2>
                <p className="leading-7">
                    Since this is a personal project, you control the policy. You can modify this file as your usage changes.
                </p>
            </section>
        </main>
    );
}
