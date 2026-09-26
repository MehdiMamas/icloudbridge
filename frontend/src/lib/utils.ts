import { type ClassValue, clsx } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

// The CalDAV URL for a Nextcloud server. The backend recognises this shape to
// tell whether Reminders uses Nextcloud, so keep the two in step.
export function nextcloudCaldavUrl(nextcloudUrl?: string | null) {
  return nextcloudUrl ? `${nextcloudUrl.replace(/\/$/, "")}/remote.php/dav` : ""
}

// Spread onto inputs for another service's credentials, so neither the browser
// nor a password manager extension fills them with a login saved for this page.
// Chrome ignores "off" on password inputs; give those autoComplete="new-password".
export const noAutofill = {
  autoComplete: "off",
  "data-1p-ignore": true,
  "data-bwignore": true,
  "data-lpignore": "true",
}
