/** The one arrow the panel uses, drawn as the public pages draw theirs. */
export function Chevron({
  direction = "right",
  className = "size-5",
}: {
  direction?: "left" | "right" | "down";
  className?: string;
}) {
  const path =
    direction === "left"
      ? "M12.5 4.5 7 10l5.5 5.5"
      : direction === "down"
        ? "M4.5 7.5 10 13l5.5-5.5"
        : "M7.5 4.5 13 10l-5.5 5.5";
  return (
    <svg aria-hidden="true" viewBox="0 0 20 20" className={`shrink-0 ${className}`}>
      <path
        d={path}
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
