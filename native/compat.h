#ifndef FT8_COMPAT_H
#define FT8_COMPAT_H
#include <string.h>
#define _USE_MATH_DEFINES
#include <math.h>
#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif
static inline char* stpcpy(char* d, const char* s) { size_t n = strlen(s); memcpy(d, s, n + 1); return d + n; }
#endif
