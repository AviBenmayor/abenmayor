"use client";
import React, { useCallback, useEffect, useState } from 'react';
import { usePlaidLink, PlaidLinkOptions, PlaidLinkOnSuccess } from 'react-plaid-link';
import { createLinkToken, exchangePublicToken } from '../lib/api';

export default function PlaidLinkButton() {
    const [token, setToken] = useState<string | null>(null);

    useEffect(() => {
        const createToken = async () => {
            try {
                console.log("Fetching link token...");
                const data = await createLinkToken("user_001");
                if (data.link_token) {
                    console.log("Link token received:", data.link_token);
                    setToken(data.link_token);
                } else {
                    console.error("No link token in response:", data);
                }
            } catch (err) {
                console.error("Failed to create link token:", err);
            }
        };
        createToken();
    }, []);

    const onSuccess = useCallback<PlaidLinkOnSuccess>((public_token, metadata) => {
        const exchange = async () => {
            await exchangePublicToken(public_token);
            alert("Bank Connected! Data will appear shortly.");
        };
        exchange();
    }, []);

    const onExit = useCallback((error: any, metadata: any) => {
        if (error != null) {
            console.error("Plaid Link Error:", error.error_code, error.error_message);
        }
        console.log("Plaid Link Exit Metadata:", metadata);
    }, []);

    const onEvent = useCallback((eventName: any, metadata: any) => {
        console.log("Plaid Link Event:", eventName, metadata);
    }, []);

    const config: PlaidLinkOptions = {
        token,
        onSuccess,
        onExit,
        onEvent,
    };

    const { open, ready } = usePlaidLink(config);

    return (
        <button
            onClick={() => open()}
            disabled={!ready}
            className="px-4 py-2 bg-black text-white rounded-md text-sm font-medium hover:bg-zinc-800 disabled:opacity-50 transition-colors"
        >
            Connect Bank
        </button>
    );
}
