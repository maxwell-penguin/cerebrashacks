import { useState } from 'react';

const trackEvent = (eventName, data) => {
  // Lightweight analytics stub
  console.log('Analytics:', eventName, data);
};

const usersData = [
  { name: 'Alice Smith', email: 'alice@example.com', role: 'Admin' },
  { name: 'Bob Jones', email: 'bob@example.com', role: 'Editor' },
  { name: 'Carol Lee', email: 'carol@example.com', role: 'Viewer' },
  { name: 'Dan Wu', email: 'dan@example.com', role: 'Editor' },
];

export default function App() {
  const [search, setSearch] = useState('');

  const filteredUsers = usersData.filter(
    ({ name, email, role }) =>
      name.toLowerCase().includes(search.toLowerCase()) ||
      email.toLowerCase().includes(search.toLowerCase()) ||
      role.toLowerCase().includes(search.toLowerCase())
  );

  const handleSearchChange = (e) => {
    const value = e.target.value;
    setSearch(value);
    trackEvent('search_input', { value });
  };

  const handleRowKeyDown = (e, email) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      trackEvent('row_activate', { email });
    }
  };

  return (
    <section className="flex flex-col p-4 space-y-4 bg-gray-50 min-h-screen">
      <h1 className="text-2xl font-bold">Users</h1>

      <input
        type="text"
        placeholder="Search..."
        aria-label="Search users"
        value={search}
        onChange={handleSearchChange}
        className="w-full md:w-1/2 p-2 border rounded focus:outline-none focus:ring-2 focus:ring-indigo-500"
      />

      <div className="overflow-x-auto rounded-lg shadow bg-white">
        <table role="table" className="min-w-full text-left border-collapse">
          <thead role="rowgroup" className="bg-gray-100">
            <tr role="row">
              <th role="columnheader" className="px-3 py-2 font-medium">
                Name
              </th>
              <th role="columnheader" className="px-3 py-2 font-medium">
                Email
              </th>
              <th role="columnheader" className="px-3 py-2 font-medium">
                Role
              </th>
            </tr>
          </thead>
          <tbody role="rowgroup">
            {filteredUsers.map(({ name, email, role }) => (
              <tr
                key={email}
                role="row"
                tabIndex={0}
                onKeyDown={(e) => handleRowKeyDown(e, email)}
                className="border-b hover:bg-gray-50"
              >
                <td role="cell" className="px-3 py-2">
                  {name}
                </td>
                <td role="cell" className="px-3 py-2">
                  {email}
                </td>
                <td role="cell" className="px-3 py-2">
                  {role}
                </td>
              </tr>
            ))}
            {filteredUsers.length === 0 && (
              <tr role="row">
                <td
                  colSpan="3"
                  role="cell"
                  className="px-3 py-2 text-center text-gray-500"
                  aria-live="polite"
                >
                  No users match your search.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}
