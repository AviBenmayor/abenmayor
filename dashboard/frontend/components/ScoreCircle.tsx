export default function ScoreCircle({ score, label, color }: { score: number, label: string, color: string }) {
    let strokeColor = "#E0E6EB";
    let textColor = "#627084";

    if (color === "red") {
        strokeColor = "#EF4444";
        textColor = "#EF4444";
    } else if (color === "green") {
        strokeColor = "#2EB877";
        textColor = "#2EB877";
    } else if (color === "yellow") {
        strokeColor = "#F59F0A";
        textColor = "#F59F0A";
    } else if (color === "blue") {
        strokeColor = "#258CF4";
        textColor = "#258CF4";
    }

    const radius = 36;
    const circumference = 2 * Math.PI * radius;
    // For Strain (0-21), we normalize to percentage for the stroke-dasharray
    const percentage = label === 'Strain' ? (score / 21) * 100 : score;
    const strokeDashoffset = circumference - (percentage / 100) * circumference;

    return (
        <div className="flex flex-col items-center">
            <div className="relative w-20 h-20 flex items-center justify-center mb-3">
                {/* SVG Ring */}
                <svg className="w-full h-full transform -rotate-90">
                    <circle
                        cx="40"
                        cy="40"
                        r={radius}
                        stroke="#F1F5F9"
                        strokeWidth="5"
                        fill="transparent"
                        className="transition-all duration-1000"
                    />
                    <circle
                        cx="40"
                        cy="40"
                        r={radius}
                        stroke={strokeColor}
                        strokeWidth="5"
                        fill="transparent"
                        strokeDasharray={circumference}
                        strokeDashoffset={strokeDashoffset}
                        strokeLinecap="round"
                        className="transition-all duration-1000 ease-out"
                    />
                </svg>
                <div className="absolute inset-0 flex items-center justify-center">
                    <span className="text-xl font-bold tracking-tighter" style={{ color: textColor }}>
                        {label === 'Strain' ? score.toFixed(1) : Math.round(score)}
                        {label !== 'Strain' && <span className="text-[10px] ml-0.5 opacity-70">%</span>}
                    </span>
                </div>
            </div>
            <span className="text-[10px] font-bold text-muted-foreground uppercase tracking-widest">{label}</span>
        </div>
    );
}
