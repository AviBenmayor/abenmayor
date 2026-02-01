"use client";
import { useState } from "react";

export default function BudgetUpload() {
    const [uploading, setUploading] = useState(false);
    const [message, setMessage] = useState("");

    const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0];
        if (!file) return;

        setUploading(true);
        setMessage("");

        const formData = new FormData();
        formData.append("file", file);

        try {
            const res = await fetch("http://localhost:8000/finance/budget/upload", {
                method: "POST",
                body: formData,
            });

            const data = await res.json();

            if (data.success) {
                setMessage(`✓ Budget uploaded! Found ${Object.keys(data.categories).length} categories.`);
                // Reload page to show new budget
                setTimeout(() => window.location.reload(), 1500);
            } else {
                setMessage(`✗ Error: ${data.error}`);
            }
        } catch (err) {
            setMessage("✗ Failed to upload budget");
            console.error(err);
        } finally {
            setUploading(false);
        }
    };

    return (
        <div className="mt-4">
            <label className="block">
                <span className="sr-only">Choose budget file</span>
                <input
                    type="file"
                    accept=".xlsx,.xls,.csv"
                    onChange={handleFileUpload}
                    disabled={uploading}
                    className="block w-full text-sm text-zinc-500
                        file:mr-4 file:py-2 file:px-4
                        file:rounded-md file:border-0
                        file:text-sm file:font-medium
                        file:bg-black file:text-white
                        hover:file:bg-zinc-800
                        file:cursor-pointer
                        disabled:opacity-50"
                />
            </label>
            {message && (
                <p className={`mt-2 text-sm ${message.startsWith('✓') ? 'text-green-600' : 'text-red-600'}`}>
                    {message}
                </p>
            )}
        </div>
    );
}
