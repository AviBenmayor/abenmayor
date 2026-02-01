# Privacy Policy for Personal Data Dashboard

**Last Updated:** December 26, 2025

## 1. Introduction
This Personal Data Dashboard is a **self-hosted**, **local-first** application designed to aggregate your personal financial and health data. This policy explains how your data is handled.

## 2. Data Collection & Storage
### Local Storage
- All data aggregated by this dashboard resides **strictly on your local machine**.
- This application **does not** transmit your data to any external server controlled by the dashboard developers.
- You are the sole custodian of your data.

### Third-Party Connections
This dashboard connects directly to the following third-party services using your credentials:
- **Plaid (Banking)**: Connects via Plaid API. Your banking credentials are not stored by this application; connection is maintained via access tokens stored locally.
- **Whoop**: Connects via Whoop API using your personal developer credentials.
- **Fidelity**: Parses CSV files provided by you. No direct connection.
- **Apple Health**: Parses XML exports provided by you. No direct connection.

## 3. Data Usage
- Data is used solely for **visualization** within the dashboard.
- No data is sold, analyzed, or shared with third parties by this application.

## 4. Security
- **API Keys**: You are responsible for keeping your API keys (`PLAID_SECRET`, etc.) secure. We recommend storing them in environment variables or a `.env` file that is not checked into version control.
- **Local Access**: Since the dashboard runs locally (`localhost`), ensure your machine is free of malware to prevent data scraping.

## 5. Changes to This Policy
Since this is a personal project, you control the policy. You can modify this file as your usage changes.
