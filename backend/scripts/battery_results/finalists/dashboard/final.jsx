import React, { useState } from 'react';

// Simple analytics stub
function trackEvent(eventName, payload) {
  console.log('Analytics:', eventName, payload);
}

export default function App() {
  const [activeNav, setActiveNav] = useState('Home');

  return (
    <div className="min-h-screen flex flex-col bg-gray-50 text-gray-800">
      <Header />
      <div className="flex flex-1 overflow-hidden">
        <Sidebar activeNav={activeNav} setActiveNav={setActiveNav} />
        <Main />
      </div>
    </div>
  );
}

function Header() {
  return (
    <header
      className="h-16 bg-white shadow flex items-center px-4"
      role="banner"
    >
      <h1 className="text-xl font-semibold">Dashboard</h1>
    </header>
  );
}

function Sidebar({ activeNav, setActiveNav }) {
  const navItems = ['Home', 'Settings', 'Reports'];
  return (
    <aside
      className="w-64 bg-white border-r hidden md:block"
      role="complementary"
      aria-label="Sidebar navigation"
    >
      <nav
        className="flex flex-col space-y-2 p-4"
        role="navigation"
        aria-label="Main navigation"
      >
        {navItems.map((item) => (
          <NavItem
            key={item}
            label={item}
            isActive={activeNav === item}
            onClick={() => {
              setActiveNav(item);
              trackEvent('nav_click', { label: item });
            }}
          />
        ))}
      </nav>
    </aside>
  );
}

function NavItem({ label, isActive, onClick }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`text-left w-full cursor-pointer transition-colors ${
        isActive
          ? 'text-blue-600 font-medium'
          : 'text-gray-600 hover:text-gray-900'
      }`}
      aria-current={isActive ? 'page' : undefined}
    >
      {label}
    </button>
  );
}

function Main() {
  return (
    <main className="flex-1 p-4 overflow-auto" role="main" aria-label="Main content">
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <StatCard title="Revenue" value="$12,400" />
        <StatCard title="Users" value="1,284" />
      </div>
    </main>
  );
}

function StatCard({ title, value }) {
  return (
    <section
      className="bg-white rounded-lg shadow p-6"
      role="region"
      aria-label={title}
    >
      <h2 className="text-sm font-medium text-gray-500">{title}</h2>
      <p className="mt-2 text-2xl font-semibold text-gray-800">{value}</p>
    </section>
  );
}
