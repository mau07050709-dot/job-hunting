// Only a tab opened for the local bridge can request an immediate check.
if (location.origin === 'http://127.0.0.1:18746' && location.pathname === '/jobmaxxing-wake') {
  chrome.runtime.sendMessage({type: 'wake'}).catch(() => {});
}
