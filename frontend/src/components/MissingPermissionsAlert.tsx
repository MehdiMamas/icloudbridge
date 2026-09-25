import { useEffect, useRef, useState } from 'react';
import { AlertTriangle, Loader2 } from 'lucide-react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import apiClient from '@/lib/api-client';
import type { PermissionsResponse, ServicePermissionStatus } from '@/types/api';

type PermissionService = 'notes' | 'reminders' | 'photos';

interface MissingPermissionsAlertProps {
  service: PermissionService;
  // Shown as "<label> requires: ..."
  label: string;
  status: ServicePermissionStatus;
  onPermissionsChange: (permissions: PermissionsResponse) => void;
}

// How long to wait for the user to answer the macOS prompts
const ANSWER_TIMEOUT_MS = 120_000;
const POLL_INTERVAL_MS = 1_500;

/**
 * Lists a service's missing macOS permissions, with a button that asks the menu
 * bar app to show the system prompts (the browser can't), then waits for the
 * answer so the page updates on its own.
 */
export function MissingPermissionsAlert({ service, label, status, onPermissionsChange }: MissingPermissionsAlertProps) {
  const [waiting, setWaiting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const requestAccess = async () => {
    setWaiting(true);
    setError(null);
    try {
      await apiClient.requestPermissions(service);
      const deadline = Date.now() + ANSWER_TIMEOUT_MS;
      while (mounted.current && Date.now() < deadline) {
        await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS));
        const permissions = await apiClient.getPermissions();
        if (!mounted.current) return;
        onPermissionsChange(permissions);
        if (permissions[service].permitted) return;
      }
    } catch (err) {
      if (mounted.current) {
        setError(err instanceof Error ? err.message : 'Could not ask macOS for permissions');
      }
    } finally {
      if (mounted.current) setWaiting(false);
    }
  };

  return (
    <Alert variant="destructive">
      <AlertTriangle className="h-4 w-4" />
      <AlertTitle>Missing Permissions</AlertTitle>
      <AlertDescription>
        <p>
          {label} requires: {status.missing.join(', ')}.
        </p>
        <Button size="sm" variant="outline" className="mt-2" onClick={requestAccess} disabled={waiting}>
          {waiting ? (
            <>
              <Loader2 className="w-4 h-4 mr-1 animate-spin" />
              Waiting for your answer in macOS…
            </>
          ) : (
            'Grant access'
          )}
        </Button>
        {error && <p className="mt-2">{error}</p>}
      </AlertDescription>
    </Alert>
  );
}

export default MissingPermissionsAlert;
