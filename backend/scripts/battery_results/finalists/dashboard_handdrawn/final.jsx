import { useState } from 'react';

function trackEvent(eventName, data) {
  console.log('Analytics:', eventName, data);
}

export default function App() {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const toggleSidebar = () => {
    trackEvent('toggle_sidebar', { open: !sidebarOpen });
    setSidebarOpen(!sidebarOpen);
  };

  const handleNavClick = (label) => {
    trackEvent('nav_click', { label });
    // Add navigation logic here if needed
  };

  return (
    <div className="flex flex-col min-h-screen">
      {/* Header */}
      <header
        className="h-16 bg-gray-800 text-white flex items-center justify-between px-4"
        role="banner"
      >
        <h1 className="text-xl font-semibold">Admin Dashboard</h1>
        <button
          className="md:hidden focus:outline-none"
          onClick={toggleSidebar}
          aria-label="Toggle menu"
          aria-expanded={sidebarOpen}
          aria-controls="sidebar"
        >
          {sidebarOpen ? (
            <svg
              className="w-6 h-6"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M6 18L18 6M6 6l12 12"
              />
            </svg>
          ) : (
            <svg
              className="w-6 h-6"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M4 6h16M4 12h16M4 18h16"
              />
            </svg>
          )}
        </button>
      </header>

      <div className="flex flex-1">
        {/* Sidebar */}
        <aside
          id="sidebar"
          className={`${
            sidebarOpen ? 'block' : 'hidden'
          } md:block w-64 bg-gray-900 text-gray-100 p-4`}
          role="complementary"
          aria-hidden={!sidebarOpen && 'true'}
        >
          <nav role="navigation" aria-label="Main navigation">
            <ul className="space-y-2">
              {['Dashboard', 'Users', 'Settings'].map((item) => (
                <li
                  key={item}
                  className="p-2 hover:bg-gray-800 rounded cursor-pointer focus:outline-none"
                  role="button"
                  tabIndex={0}
                  onClick={() => handleNavClick(item)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault();
                      handleNavClick(item);
                    }
                  }}
                >
                  {item}
                </li>
              ))}
            </ul>
          </nav>
        </aside>

        {/* Main content */}
        <main className="flex-1 p-4 overflow-auto" role="main">
          {/* Stat cards */}
          <section className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <StatCard title="Total Users" value="1,234" />
            <StatCard title="Revenue" value="$12,345" />
          </section>

          {/* Image container */}
          <section className="mt-6">
            <ImageContainer />
          </section>
        </main>
      </div>
    </div>
  );
}

function StatCard({ title, value }) {
  const handleClick = () => {
    trackEvent('stat_card_click', { title });
  };

  return (
    <div
      className="bg-white rounded-lg shadow p-6 flex items-center justify-between"
      role="button"
      tabIndex={0}
      onClick={handleClick}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          handleClick();
        }
      }}
    >
      <div>
        <h2 className="text-sm font-medium text-gray-500">{title}</h2>
        <p className="text-2xl font-semibold text-gray-800">{value}</p>
      </div>
      <svg
        className="w-8 h-8 text-gray-300"
        fill="none"
        stroke="currentColor"
        viewBox="0 0 24 24"
        aria-hidden="true"
      >
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth={2}
          d="M13 16h-1v-4h-1m1-4h.01"
        />
      </svg>
    </div>
  );
}

function ImageContainer() {
  const handleClick = () => {
    trackEvent('image_container_click', {});
  };

  return (
    <div
      className="bg-gray-100 rounded-lg h-64 md:h-96 flex items-center justify-center"
      role="button"
      tabIndex={0}
      onClick={handleClick}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          handleClick();
        }
      }}
      aria-label="Image area"
    >
      <span className="text-gray-500 text-lg">Image Area</span>
    </div>
  );
}
