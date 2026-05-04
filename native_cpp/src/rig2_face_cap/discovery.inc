bool normalize_ipv4_address(const std::string& address, std::string* normalized) {
  if (!normalized) {
    return false;
  }
  normalized->clear();

  std::string input = address;
  input.erase(input.begin(), std::find_if(input.begin(), input.end(), [](unsigned char c) {
                return !std::isspace(c);
              }));
  input.erase(
      std::find_if(input.rbegin(), input.rend(), [](unsigned char c) { return !std::isspace(c); }).base(),
      input.end());
  if (input.empty()) {
    return false;
  }

  in_addr addr{};
  if (inet_pton(AF_INET, input.c_str(), &addr) != 1) {
    return false;
  }

  char buffer[INET_ADDRSTRLEN] = {0};
  if (!inet_ntop(AF_INET, &addr, buffer, sizeof(buffer))) {
    return false;
  }

  *normalized = buffer;
  return true;
}

bool is_preferred_lan_ipv4(const std::string& address) {
  in_addr addr{};
  if (inet_pton(AF_INET, address.c_str(), &addr) != 1) {
    return false;
  }

  uint32_t host = ntohl(addr.s_addr);
  const uint8_t octet1 = static_cast<uint8_t>((host >> 24) & 0xFF);
  const uint8_t octet2 = static_cast<uint8_t>((host >> 16) & 0xFF);

  if (host == 0) {
    return false;
  }
  if (octet1 == 127) {
    return false;
  }
  if (octet1 == 169 && octet2 == 254) {
    return false;
  }

  return true;
}

void add_candidate_ipv4(
    const std::string& address,
    std::vector<std::string>* candidates,
    std::vector<std::string>* seen) {
  if (!candidates || !seen) {
    return;
  }

  std::string normalized;
  if (!normalize_ipv4_address(address, &normalized)) {
    return;
  }

  if (std::find(seen->begin(), seen->end(), normalized) != seen->end()) {
    return;
  }

  seen->push_back(normalized);
  candidates->push_back(normalized);
}

std::string discover_local_ipv4_impl(const std::string& preferred_host) {
  std::string normalized_host;
  normalize_ipv4_address(preferred_host, &normalized_host);

  if (!normalized_host.empty() && is_preferred_lan_ipv4(normalized_host)) {
    return normalized_host;
  }

  std::vector<std::string> candidates;
  std::vector<std::string> seen;

  if (!normalized_host.empty() && normalized_host != "0.0.0.0") {
    add_candidate_ipv4(normalized_host, &candidates, &seen);
  }

  const std::array<std::pair<const char*, uint16_t>, 2> probe_targets = {
      std::make_pair("192.0.2.1", 80),
      std::make_pair("8.8.8.8", 80),
  };

  for (const auto& target : probe_targets) {
    int sock = static_cast<int>(socket(AF_INET, SOCK_DGRAM, 0));
#if defined(_WIN32)
    if (sock == INVALID_SOCKET) {
      continue;
    }
#else
    if (sock < 0) {
      continue;
    }
#endif

    sockaddr_in remote{};
    remote.sin_family = AF_INET;
    remote.sin_port = htons(target.second);
    if (inet_pton(AF_INET, target.first, &remote.sin_addr) == 1) {
      if (connect(sock, reinterpret_cast<sockaddr*>(&remote), sizeof(remote)) == 0) {
        sockaddr_in local{};
        socklen_t len = static_cast<socklen_t>(sizeof(local));
        if (getsockname(sock, reinterpret_cast<sockaddr*>(&local), &len) == 0) {
          char ip_text[INET_ADDRSTRLEN] = {0};
          if (inet_ntop(AF_INET, &local.sin_addr, ip_text, sizeof(ip_text))) {
            add_candidate_ipv4(ip_text, &candidates, &seen);
          }
        }
      }
    }

#if defined(_WIN32)
    closesocket(sock);
#else
    close(sock);
#endif
  }

  for (const std::string& candidate : candidates) {
    if (is_preferred_lan_ipv4(candidate)) {
      return candidate;
    }
  }

  if (!normalized_host.empty() && normalized_host != "0.0.0.0") {
    return normalized_host;
  }

  for (const std::string& candidate : candidates) {
    if (candidate != "0.0.0.0") {
      return candidate;
    }
  }

  return std::string();
}
