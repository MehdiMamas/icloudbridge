# iCloudBridge Frontend

Modern web interface for iCloudBridge - Sync Apple Notes, Reminders, and Passwords.

## Tech Stack

- **React 18** - UI framework
- **TypeScript** - Type safety
- **Vite** - Build tool
- **Tailwind CSS** - Styling
- **shadcn/ui** - UI components
- **Zustand** - State management
- **Axios** - HTTP client
- **React Router** - Navigation

## Getting Started

### Prerequisites

- Node.js 20.19+ and npm
- iCloudBridge API server running (default: http://localhost:8000)

### Installation

```bash
# Install dependencies
npm install
```

### Development

```bash
# Start dev server (http://localhost:3000)
npm run dev
```

The dev server includes:
- Hot module replacement
- Proxy to API server at /api -> http://localhost:8000
- WebSocket proxy at /api/ws

### Build

```bash
# Build for production
npm run build

# Preview production build
npm run preview
```

## Project Structure

```
frontend/
├── src/
│   ├── components/
│   │   ├── Layout.tsx          # Main layout with sidebar
│   │   └── ui/                 # shadcn/ui components
│   ├── pages/
│   │   ├── Dashboard.tsx       # Status overview
│   │   ├── Notes.tsx           # Notes sync
│   │   ├── Reminders.tsx       # Reminders sync
│   │   ├── Passwords.tsx       # Passwords sync
│   │   ├── Schedules.tsx       # Schedule management
│   │   └── Settings.tsx        # Configuration
│   ├── store/
│   │   ├── app-store.ts        # Global app state
│   │   ├── sync-store.ts       # Sync operations state
│   │   └── schedules-store.ts  # Schedules state
│   ├── hooks/
│   │   └── useWebSocket.ts     # WebSocket hook
│   ├── lib/
│   │   ├── api-client.ts       # API client
│   │   └── utils.ts            # Utilities
│   ├── types/
│   │   └── api.ts              # TypeScript types
│   ├── App.tsx                 # Root component
│   ├── main.tsx                # Entry point
│   └── index.css               # Global styles
├── package.json
├── tsconfig.json
├── vite.config.ts
└── tailwind.config.js
```

## Features

### Real-Time Updates
- WebSocket connection for live sync progress
- Auto-reconnect with exponential backoff
- Real-time logs and notifications

### Pages

#### Dashboard
- Service status overview
- Active sync indicators
- Recent activity logs
- Scheduler status

#### Notes Sync
- Import, export, or bidirectional sync
- Notes folders list
- Sync history
- Live progress tracking

#### Reminders Sync
- Auto (iCloud) or manual (CalDAV) mode
- CalDAV password management
- Calendars list
- Sync history

#### Passwords Sync
- VaultWarden integration
- Import/export Apple and Bitwarden CSV
- Credentials management
- Sync history

#### Schedules
- Create interval or cron-based schedules
- Toggle schedules on/off
- Manual trigger
- Filter by service

#### Settings
- iCloud configuration
- Service enable/disable
- Connection testing
- Configuration validation

## Development

### Adding a New shadcn/ui Component

```bash
# Example: Add a dialog component
npx shadcn-ui@latest add dialog
```

### State Management

The app uses Zustand for state management:

- `app-store.ts` - Global state (config, theme, UI)
- `sync-store.ts` - Sync operations and logs
- `schedules-store.ts` - Schedule management

### API Integration

All API calls go through the centralized API client:

```typescript
import apiClient from '@/lib/api-client';

// Example usage
const schedules = await apiClient.getSchedules();
await apiClient.syncNotes({ mode: 'bidirectional' });
```

### WebSocket Integration

Use the `useWebSocket` hook for real-time updates:

```typescript
import { useWebSocket } from '@/hooks/useWebSocket';

const { isConnected } = useWebSocket({
  onSyncProgress: (service, data) => {
    // Handle sync progress
  },
  onLogEntry: (service, data) => {
    // Handle log entry
  },
});
```

## Environment Variables

Create `.env` file for custom configuration:

```env
# API base URL (default: /api via proxy)
VITE_API_BASE_URL=http://localhost:8000/api

# WebSocket URL (default: ws://localhost:8000/api/ws via proxy)
VITE_WS_URL=ws://localhost:8000/api/ws
```

## Browser Support

- Chrome/Edge (latest)
- Firefox (latest)
- Safari (latest)

## License

See main project LICENSE
