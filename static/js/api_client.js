(function(root) {
    class ApiClient {
        /**
         * @param {Object} config - Configuration options
         * @param {string} [config.namespace=''] - API namespace (prefix)
         * @param {string} [config.authTokenKey='auth_token'] - LocalStorage key for auth token
         * @param {string} [config.loginUrl='/login/'] - URL to redirect on 401
         */
        constructor(config = {}) {
            this.config = Object.assign({
                namespace: '',
                authTokenKey: 'auth_token',
                loginUrl: '/login/'
            }, config);
        }

        /**
         * Computes the base URL based on the namespace.
         */
        get baseUrl() {
            if (!this.config.namespace) return '/';
            // Trim slashes to ensure cleaner URL construction
            const ns = this.config.namespace.replace(/^\/+|\/+$/g, '');
            return `/${ns}/`;
        }

        /**
         * Retrieves the CSRF token from cookies.
         */
        getCsrfToken() {
            if (document.cookie && document.cookie !== '') {
                const cookies = document.cookie.split(';');
                for (let i = 0; i < cookies.length; i++) {
                    const cookie = cookies[i].trim();
                    if (cookie.substring(0, 10) === ('csrftoken=')) {
                        return decodeURIComponent(cookie.substring(10));
                    }
                }
            }
            return '';
        }

        /**
         * Sets the authentication token.
         * @param {string} token 
         */
        setToken(token) {
            localStorage.setItem(this.config.authTokenKey, token);
        }

        /**
         * Gets the authentication token.
         * @returns {string|null}
         */
        getToken() {
            return localStorage.getItem(this.config.authTokenKey);
        }

        /**
         * Removes the authentication token.
         */
        removeToken() {
            localStorage.removeItem(this.config.authTokenKey);
        }

        /**
         * Checks if the user is authenticated.
         * @returns {boolean}
         */
        isAuthenticated() {
            return !!this.getToken();
        }

        /**
         * Core request method.
         * @param {string} endpoint - The API endpoint (relative to baseUrl)
         * @param {Object} opts - Fetch options
         */
        async request(endpoint, opts = {}) {
            // Normalize endpoint: remove leading slash if present to avoid double slashes 
            // when combined with baseUrl (which always ends in slash)
            const cleanEndpoint = endpoint.replace(/^\/+/, '');
            const url = `${this.baseUrl}${cleanEndpoint}`;

            const headers = {
                'X-CSRFToken': this.getCsrfToken(),
                ...(opts.headers || {})
            };

            // Add Authorization header if token exists
            const token = this.getToken();
            if (token) {
                headers['Authorization'] = `Bearer ${token}`;
            }

            // Set Content-Type only if not FormData
            if (!(opts.body instanceof FormData)) {
                headers['Content-Type'] = headers['Content-Type'] || 'application/json';
            } else {
                 // Let browser set boundary for FormData
                 delete headers['Content-Type'];
            }

            try {
                const res = await fetch(url, { ...opts, headers });
                
                // Handle 401 Unauthorized
                if (res.status === 401) {
                    this.removeToken();
                    if (this.config.loginUrl && window.location.pathname !== this.config.loginUrl) {
                        window.location.href = this.config.loginUrl;
                        throw new Error('Unauthorized');
                    }
                }

                // Direct response return for stream or raw requests
                if (opts.raw) { return res; }

                // Attempt to parse JSON
                let data;
                try {
                    data = await res.json();
                } catch (jsonErr) {
                    // If JSON parsing fails, use text or empty object
                    // This handles empty responses (204) or non-JSON errors
                    data = { message: res.statusText };
                }

                if (!res.ok) {
                    const errorMsg = (data && (data.message || data.error)) ? (data.message || data.error) : '请求失败';
                    const error = new Error(errorMsg);
                    error.data = data; // Attach response data to error
                    error.status = res.status;
                    throw error;
                }
                
                return data;
            } catch (error) {
                // If it's a network error or fetch failure not caught above
                if (!error.status && !error.data) {
                    // It might be a network error
                    console.error('API Network Error for ' + endpoint, error);
                }
                throw error;
            }
        }

        get(endpoint, params = {}) {
            let url = endpoint;
            if (params && Object.keys(params).length > 0) {
                const queryString = new URLSearchParams(params).toString();
                url += (url.includes('?') ? '&' : '?') + queryString;
            }
            return this.request(url, { method: 'GET' });
        }

        post(endpoint, data, opts = {}) {
            const isFormData = data instanceof FormData;
            return this.request(endpoint, {
                method: 'POST',
                body: isFormData ? data : JSON.stringify(data),
                ...opts
            });
        }

        put(endpoint, data) {
            return this.request(endpoint, { method: 'PUT', body: JSON.stringify(data) });
        }

        delete(endpoint) {
            return this.request(endpoint, { method: 'DELETE' });
        }
        
        patch(endpoint, data) {
            return this.request(endpoint, { method: 'PATCH', body: JSON.stringify(data) });
        }
    }

    // Export module
    if (typeof define === 'function' && define.amd) {
        define([], () => ApiClient);
    } else if (typeof module === 'object' && module.exports) {
        module.exports = ApiClient;
    } else {
        root.ApiClient = ApiClient;
    }
}(typeof self !== 'undefined' ? self : this));
