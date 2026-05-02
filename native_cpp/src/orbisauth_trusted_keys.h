#pragma once

namespace rig2_trust {

constexpr const char* kDefaultTrustedJwksJson = R"json({
  "keys": [
    {
      "alg": "RS256",
      "e": "AQAB",
      "kid": "orbisauth-rs256-v1",
      "kty": "RSA",
      "n": "u8IQrp9JIzV--8hX-eTgfEox95KEv-kP5UxX5QhBd53Rdz3foSA_PgfWL-hc79wMYouupEBRUqomQBaDM1Yoi4-leB8HF_4pdRGuS-ZjgfV2whnykSVDjyGy6k37lga5nL43_N68u79NRl9CxqJfex-wayvT11-pj4WxXsYHlp4AOHEPeIbGPEYZqW5dMz-uONdXVyDL9MT1wOfsCvkOsDRNC8P3bg3z-VRs68q-rQ-ScgFJ0ROAAMUirURjs7GQJEOnwCoKyASfup2AxZ2knKaKmY6FGHc3BJ15uGhApIXntae7BVd28En3QcEo2T7drrJN3IqirIMZRyuhhpV-NQ",
      "use": "sig"
    }
  ]
})json";

}  // namespace rig2_trust
