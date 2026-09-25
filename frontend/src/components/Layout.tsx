import { useEffect, useState } from 'react';
import { Link, Outlet, useLocation } from 'react-router-dom';
import {
  LayoutDashboard,
  FileText,
  Calendar,
  Key,
  Image,
  Clock,
  Terminal,
  Settings,
  Moon,
  Sun,
  Monitor,
  Menu,
  X,
  HelpCircle,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';
import { useAppStore } from '@/store/app-store';
import { useSyncStore } from '@/store/sync-store';
import { useWebSocket } from '@/hooks/useWebSocket';
import FirstRunWizard from '@/components/FirstRunWizard';

export default function Layout() {
  const location = useLocation();
  const [appVersion, setAppVersion] = useState<string>(__APP_VERSION__ ?? '…');
  const {
    theme,
    setTheme,
    sidebarOpen,
    toggleSidebar,
    wsConnected,
    setWsConnected,
    dataRevision,
  } = useAppStore();
  const { setActiveSync, clearActiveSync, addLog, addScheduleRun } = useSyncStore();

  // WebSocket connection for real-time updates (optional)
  const { isConnected } = useWebSocket({
    autoConnect: true,
    maxReconnectAttempts: 3, // Reduce reconnection attempts to avoid noise
    reconnectInterval: 10000, // Wait 10s between reconnection attempts
    onOpen: () => setWsConnected(true),
    onClose: () => setWsConnected(false),
    onSyncProgress: (service, data) => {
      if (data.status === 'running') {
        setActiveSync(service, data);
      } else {
        clearActiveSync(service);
      }
    },
    onLogEntry: (service, data) => {
      addLog(service, data.level, data.message);
    },
    onScheduleRun: (service, data) => {
      addScheduleRun(data.schedule_id, data.schedule_name, service, data.status);
    },
  });

  useEffect(() => {
    setWsConnected(isConnected);
  }, [isConnected, setWsConnected]);

  useEffect(() => {
    const controller = new AbortController();

    const loadVersion = async () => {
      try {
        const response = await fetch('/api/version', { signal: controller.signal });
        if (!response.ok) {
          throw new Error(`Version fetch failed: ${response.status}`);
        }
        const data: { version?: string } = await response.json();
        setAppVersion(data.version ?? __APP_VERSION__);
      } catch (error) {
        if ((error as Error).name !== 'AbortError') {
          setAppVersion(__APP_VERSION__);
        }
      }
    };

    loadVersion();
    return () => controller.abort();
  }, []);

  const navigation = [
    { name: 'Dashboard', href: '/', icon: LayoutDashboard },
    { name: 'Notes', href: '/notes', icon: FileText },
    { name: 'Reminders', href: '/reminders', icon: Calendar },
    { name: 'Passwords', href: '/passwords', icon: Key },
    { name: 'Photos', href: '/photos', icon: Image },
    { name: 'Schedules', href: '/schedules', icon: Clock },
    { name: 'Logs', href: '/logs', icon: Terminal },
    { name: 'Settings', href: '/settings', icon: Settings },
  ];
  const themeOptions = [
    { value: 'light', label: 'Light', icon: Sun },
    { value: 'dark', label: 'Dark', icon: Moon },
    { value: 'system', label: 'Match system', icon: Monitor },
  ] as const;

  return (
    <div className="h-screen flex overflow-hidden bg-background">
      {/* Sidebar */}
      <div
        className={`${
          sidebarOpen ? 'translate-x-0' : '-translate-x-full'
        } fixed inset-y-0 left-0 z-50 w-64 bg-card border-r transition-transform duration-300 ease-in-out lg:translate-x-0 lg:static lg:inset-0`}
      >
        <div className="h-full flex flex-col">
          {/* Logo */}
          <div className="h-16 flex items-center justify-between px-6 border-b">
            <div className="flex items-center gap-3">
              <img
                src="/icloudbridge_dark_650.png"
                alt="iCloudBridge"
                className="h-10 w-auto rounded-md shadow-sm dark:hidden"
              />
              <img
                src="/icloudbridge_light_650.png"
                alt="iCloudBridge"
                className="h-10 w-auto rounded-md shadow-sm hidden dark:block"
              />
              <span className="font-semibold text-lg">iCloudBridge</span>
            </div>
            <Button
              variant="ghost"
              size="icon"
              className="lg:hidden"
              onClick={toggleSidebar}
            >
              <X className="w-5 h-5" />
            </Button>
          </div>

          {/* Navigation */}
          <nav className="flex-1 px-3 py-4 space-y-1 overflow-y-auto">
            {navigation.map((item) => {
              const isActive = location.pathname === item.href;
              const Icon = item.icon;
              return (
                <Link
                  key={item.name}
                  to={item.href}
                  className={`flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
                    isActive
                      ? 'bg-primary text-primary-foreground'
                      : 'text-muted-foreground hover:bg-accent hover:text-accent-foreground'
                  }`}
                >
                  <Icon className="w-5 h-5" />
                  {item.name}
                </Link>
              );
            })}
          </nav>

          {/* Footer */}
          <div className="p-4 border-t space-y-2">
            <div className="flex items-center justify-between text-xs text-muted-foreground">
              <span>WebSocket</span>
              <Badge variant={wsConnected ? 'success' : 'destructive'} className="text-xs">
                {wsConnected ? 'Connected' : 'Disconnected'}
              </Badge>
            </div>
            <TooltipProvider>
              <Popover>
                <PopoverTrigger asChild>
                  <Button variant="outline" size="icon" className="w-full h-10">
                    {theme === 'dark' ? (
                      <Moon className="w-4 h-4" />
                    ) : theme === 'light' ? (
                      <Sun className="w-4 h-4" />
                    ) : (
                      <Monitor className="w-4 h-4" />
                    )}
                    <span className="sr-only">Toggle theme</span>
                  </Button>
                </PopoverTrigger>
                <PopoverContent className="w-48">
                  <div className="flex items-center justify-between gap-2">
                    {themeOptions.map((option) => (
                      <Tooltip key={option.value} delayDuration={0}>
                        <TooltipTrigger asChild>
                          <Button
                            type="button"
                            variant={theme === option.value ? 'default' : 'ghost'}
                            size="icon"
                            className="h-10 w-10"
                            onClick={() => setTheme(option.value)}
                          >
                            <option.icon className="w-4 h-4" />
                            <span className="sr-only">{option.label}</span>
                          </Button>
                        </TooltipTrigger>
                        <TooltipContent>{option.label}</TooltipContent>
                      </Tooltip>
                    ))}
                  </div>
                </PopoverContent>
              </Popover>
            </TooltipProvider>
          </div>
        </div>
      </div>

      {/* Main Content */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Header */}
        <header className="h-16 border-b bg-card flex items-center justify-between px-6 lg:px-8">
          <Button
            variant="ghost"
            size="icon"
            className="lg:hidden"
            onClick={toggleSidebar}
          >
            <Menu className="w-5 h-5" />
          </Button>
          <div className="flex items-center gap-4">
            <TooltipProvider>
              <Tooltip delayDuration={0}>
                <TooltipTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon"
                    asChild
                  >
                    <a
                      href="https://docs.icloudbridge.app"
                      target="_blank"
                      rel="noopener noreferrer"
                      aria-label="Documentation"
                    >
                      <HelpCircle className="w-5 h-5" />
                    </a>
                  </Button>
                </TooltipTrigger>
                <TooltipContent>Documentation</TooltipContent>
              </Tooltip>
            </TooltipProvider>
            <Badge variant="outline">v{appVersion}</Badge>
          </div>
        </header>

        {/* Page Content */}
        <main className="flex-1 overflow-y-auto p-6 lg:p-8">
          {/* Keyed so refreshData() remounts the page and it reloads its data */}
          <Outlet key={dataRevision} />
        </main>
      </div>

      {/* Overlay for mobile */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 bg-black/50 z-40 lg:hidden"
          onClick={toggleSidebar}
        />
      )}

      <FirstRunWizard />
    </div>
  );
}
