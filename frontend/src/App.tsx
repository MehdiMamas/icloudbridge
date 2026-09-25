import { useEffect } from 'react';
import { createBrowserRouter, RouterProvider } from 'react-router-dom';
import Layout from './components/Layout';
import Dashboard from './pages/Dashboard';
import Notes from './pages/Notes';
import Reminders from './pages/Reminders';
import Passwords from './pages/Passwords';
import Photos from './pages/Photos';
import Schedules from './pages/Schedules';
import Logs from './pages/Logs';
import Settings from './pages/Settings';
import { FIRST_RUN_COMPLETED_SETTING, useAppStore } from './store/app-store';
import apiClient from './lib/api-client';

const router = createBrowserRouter([
  {
    path: '/',
    element: <Layout />,
    children: [
      { index: true, element: <Dashboard /> },
      { path: 'notes', element: <Notes /> },
      { path: 'reminders', element: <Reminders /> },
      { path: 'passwords', element: <Passwords /> },
      { path: 'photos', element: <Photos /> },
      { path: 'schedules', element: <Schedules /> },
      { path: 'logs', element: <Logs /> },
      { path: 'settings', element: <Settings /> },
    ],
  },
]);

function App() {
  const { setIsFirstRun, theme, setTheme } = useAppStore();

  // Apply theme on initial load
  useEffect(() => {
    setTheme(theme);
  }, [theme, setTheme]);

  useEffect(() => {
    if (theme !== 'system') {
      return;
    }
    const media = window.matchMedia('(prefers-color-scheme: dark)');
    const handler = () => setTheme('system');
    media.addEventListener('change', handler);
    return () => media.removeEventListener('change', handler);
  }, [theme, setTheme]);

  useEffect(() => {
    // Check if this is first run by trying to load config
    const checkFirstRun = async () => {
      try {
        // The backend records a completed wizard, not this browser: a fresh or
        // wiped backend must show the wizard even to a browser that saw it before.
        const completed = await apiClient.getSetting(FIRST_RUN_COMPLETED_SETTING).catch(() => null);
        if (completed === 'true') {
          console.log('Wizard already completed, skipping first run');
          setIsFirstRun(false);
          return;
        }

        // Try to fetch config to see if app has been configured
        const config = await apiClient.getConfig();
        console.log('Config loaded:', config);

        // If at least one service is configured with its required settings, consider app configured
        const isConfigured =
          (config.notes_enabled && config.notes_remote_folder) ||
          (config.reminders_enabled && config.reminders_caldav_url && config.reminders_caldav_username) ||
          (config.passwords_enabled && config.passwords_vaultwarden_url && config.passwords_vaultwarden_email) ||
          config.photos_enabled;

        if (isConfigured) {
          // Installs that finished the wizard before the backend recorded it
          console.log('Found configured services, marking wizard as complete');
          await apiClient
            .updateSettings([{ key: FIRST_RUN_COMPLETED_SETTING, value: 'true' }])
            .catch((err) => console.warn('Failed to record wizard completion:', err));
          setIsFirstRun(false);
        } else {
          console.log('No services configured, showing first run wizard');
          setIsFirstRun(true);
        }
      } catch (err) {
        // If config fetch fails, assume first run
        console.error('Failed to check first run status:', err);
        setIsFirstRun(true);
      }
    };

    checkFirstRun();
  }, [setIsFirstRun]);

  // The first-run wizard is rendered by Layout, inside the router, so it can
  // control which page sits behind it.
  return <RouterProvider router={router} />;
}

export default App;
