void close_socket(SocketHandle* socket_handle) {
  if (!socket_handle || *socket_handle == kInvalidSocket) {
    return;
  }
#if defined(_WIN32)
  closesocket(*socket_handle);
#else
  close(*socket_handle);
#endif
  *socket_handle = kInvalidSocket;
}

void shutdown_socket(SocketHandle socket_handle) {
  if (socket_handle == kInvalidSocket) {
    return;
  }
#if defined(_WIN32)
  shutdown(socket_handle, SD_BOTH);
#else
  shutdown(socket_handle, SHUT_RDWR);
#endif
}

void configure_connected_socket(SocketHandle socket_handle) {
  if (socket_handle == kInvalidSocket) {
    return;
  }
#if !defined(_WIN32) && defined(SO_NOSIGPIPE)
  int enable_no_sigpipe = 1;
  setsockopt(
      socket_handle,
      SOL_SOCKET,
      SO_NOSIGPIPE,
      reinterpret_cast<const char*>(&enable_no_sigpipe),
      sizeof(enable_no_sigpipe));
#endif
}

bool send_all(SocketHandle socket_handle, const char* data, size_t size) {
  if (socket_handle == kInvalidSocket || !data) {
    return false;
  }
  size_t sent = 0;
  while (sent < size) {
#if defined(_WIN32)
    const int rc = send(socket_handle, data + sent, static_cast<int>(size - sent), 0);
#elif defined(MSG_NOSIGNAL)
    const ssize_t rc = send(socket_handle, data + sent, size - sent, MSG_NOSIGNAL);
#else
    const ssize_t rc = send(socket_handle, data + sent, size - sent, 0);
#endif
    if (rc <= 0) {
      return false;
    }
    sent += static_cast<size_t>(rc);
  }
  return true;
}

bool wait_socket_readable(SocketHandle socket_handle, int timeout_ms) {
  if (socket_handle == kInvalidSocket) {
    return false;
  }

  fd_set readfds;
  FD_ZERO(&readfds);
  FD_SET(socket_handle, &readfds);

  timeval tv{};
  tv.tv_sec = timeout_ms / 1000;
  tv.tv_usec = (timeout_ms % 1000) * 1000;

#if defined(_WIN32)
  const int rc = select(0, &readfds, nullptr, nullptr, &tv);
#else
  const int rc = select(socket_handle + 1, &readfds, nullptr, nullptr, &tv);
#endif
  return rc > 0 && FD_ISSET(socket_handle, &readfds);
}

bool recv_append(
    SocketHandle socket_handle,
    std::vector<unsigned char>* buffer,
    std::vector<unsigned char>* scratch,
    size_t chunk_size) {
  if (socket_handle == kInvalidSocket || !buffer || !scratch || chunk_size == 0) {
    return false;
  }

  if (scratch->size() < chunk_size) {
    scratch->resize(chunk_size);
  }
#if defined(_WIN32)
  const int rc = recv(socket_handle, reinterpret_cast<char*>(scratch->data()), static_cast<int>(chunk_size), 0);
#else
  const ssize_t rc = recv(socket_handle, scratch->data(), chunk_size, 0);
#endif
  if (rc <= 0) {
    return false;
  }
  const size_t received = static_cast<size_t>(rc);
  buffer->insert(buffer->end(), scratch->begin(), scratch->begin() + static_cast<std::ptrdiff_t>(received));
  return true;
}

bool recv_until_marker(
    FaceCapReceiverState* state,
    SocketHandle socket_handle,
    std::vector<unsigned char>* buffer,
    std::vector<unsigned char>* scratch,
    const std::string& marker,
    std::string* out) {
  if (!state || socket_handle == kInvalidSocket || !buffer || !scratch || !out) {
    return false;
  }

  while (!state->stop_requested.load()) {
    const auto found = std::search(buffer->begin(), buffer->end(), marker.begin(), marker.end());
    if (found != buffer->end()) {
      const size_t end_index = static_cast<size_t>(std::distance(buffer->begin(), found)) + marker.size();
      out->assign(buffer->begin(), buffer->begin() + static_cast<std::ptrdiff_t>(end_index));
      buffer->erase(buffer->begin(), buffer->begin() + static_cast<std::ptrdiff_t>(end_index));
      return true;
    }
    if (!wait_socket_readable(socket_handle, kReceiverSocketTimeoutMs)) {
      continue;
    }
    if (!recv_append(socket_handle, buffer, scratch, 4096)) {
      return false;
    }
  }
  return false;
}

bool read_exact(
    FaceCapReceiverState* state,
    SocketHandle socket_handle,
    std::vector<unsigned char>* buffer,
    std::vector<unsigned char>* scratch,
    size_t size,
    std::vector<unsigned char>* out) {
  if (!state || socket_handle == kInvalidSocket || !buffer || !scratch || !out) {
    return false;
  }

  while (!state->stop_requested.load() && buffer->size() < size) {
    if (!wait_socket_readable(socket_handle, kReceiverSocketTimeoutMs)) {
      continue;
    }
    if (!recv_append(socket_handle, buffer, scratch, (std::max)(size_t(4096), size - buffer->size()))) {
      return false;
    }
  }

  if (buffer->size() < size) {
    return false;
  }

  out->assign(buffer->begin(), buffer->begin() + static_cast<std::ptrdiff_t>(size));
  buffer->erase(buffer->begin(), buffer->begin() + static_cast<std::ptrdiff_t>(size));
  return true;
}
