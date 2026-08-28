import { useId, useState } from 'react'
import './RecapSection.css'

/*
    The heading strip every recap section wears, plus the "About" toggle that
    explains what the section is showing.

    The banner has to sit below the strip rather than inside it — the strip is a
    flex row — so this renders the two as siblings in a fragment. Sections
    without an `about` get just the heading, and no button.
*/
export default function SectionHead({ title, about }) {
    const [open, setOpen] = useState(false);
    // Ties the button to the banner it controls, uniquely per section instance.
    const bannerId = useId();

    return (
        <>
            <div className="section-head">
                <h2>{title}</h2>
                {about && (
                    <button
                        type="button"
                        className="section-about-btn"
                        aria-expanded={open}
                        aria-controls={bannerId}
                        onClick={() => setOpen((isOpen) => !isOpen)}
                    >
                        About
                    </button>
                )}
            </div>

            {about && open && (
                <div className="section-about" id={bannerId}>
                    {about}
                </div>
            )}
        </>
    );
}
