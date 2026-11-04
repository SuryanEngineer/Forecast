import { X } from 'lucide-react';

/** Close button that stays pinned at the top of a scrolling pop-up on phones (the normal header X scrolls out of view).
 * Hidden on desktop; the pop-up's own X is hidden on phones (see .modal-scroll in theme.css). */
export function MobileClose({ onClose }: { onClose: () => void }) {
  return (
    <div className="mobile-only sticky top-0 z-30 h-0">
      <button
        onClick={onClose}
        aria-label="Close"
        className="mobile-close absolute flex items-center justify-center rounded-full"
        style={{ top: 8, right: 8, width: 40, height: 40, background: 'rgba(2,6,16,0.82)', border: '1px solid var(--border)', backdropFilter: 'blur(6px)' }}
      >
        <X className="w-5 h-5 text-foreground" />
      </button>
    </div>
  );
}
