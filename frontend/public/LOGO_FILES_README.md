# Math2Visual Logo and Icon Files

This directory contains logo and icon files for the Math2Visual web application, generated from the original SVG logo.

## Source Files

- `math2visual-logo-m2v.svg` - Original rectangular logo (80x40)
- `math2visual-logo-square.svg` - Square version for icons (80x80)

## Generated Files

### Square Icons (for app icons, favicons, and web app manifests)

- `favicon.ico` - Multi-size favicon (16x16, 32x32, 48x48) - 29KB
- `favicon-16x16.png` - Small favicon size - 549 bytes
- `favicon-32x32.png` - Medium favicon size - 835 bytes
- `apple-touch-icon.png` - iOS home screen icon (180x180) - 8.6KB
- `android-chrome-256x256.png` - Android Chrome icon (256x256) - 16KB
- `logo192.png` - PWA manifest icon (192x192) - 9.8KB
- `logo512.png` - PWA manifest icon (512x512) - 56KB

### Rectangular Logo (for web app header/branding)

- `math2visual-logo-400x200.png` - Web header logo (400x200) - 33KB

## Usage

### In HTML `<head>`

```html
<link rel="icon" type="image/x-icon" href="/favicon.ico">
<link rel="icon" type="image/png" sizes="32x32" href="/favicon-32x32.png">
<link rel="icon" type="image/png" sizes="16x16" href="/favicon-16x16.png">
<link rel="apple-touch-icon" sizes="180x180" href="/apple-touch-icon.png">
```

### In Web App Manifest

```json
{
  "icons": [
    {
      "src": "logo192.png",
      "type": "image/png",
      "sizes": "192x192"
    },
    {
      "src": "logo512.png",
      "type": "image/png",
      "sizes": "512x512"
    }
  ]
}
```

### In React Components

```tsx
// For header/branding
<img src="/math2visual-logo-400x200.png" alt="Math2Visual" />
```
 