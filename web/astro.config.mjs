// @ts-check
import { defineConfig } from 'astro/config';

// Frontend estático (SSG). Habla con el backend Python en http://127.0.0.1:8000
// por fetch desde el navegador. En dev, el server corre en el puerto 4321.
export default defineConfig({
  server: { port: 4321 },
});
