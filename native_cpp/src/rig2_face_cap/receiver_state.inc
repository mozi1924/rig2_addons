#if defined(_WIN32)
using SocketHandle = SOCKET;
constexpr SocketHandle kInvalidSocket = INVALID_SOCKET;
#else
using SocketHandle = int;
constexpr SocketHandle kInvalidSocket = -1;
#endif

double now_seconds() {
  using Clock = std::chrono::system_clock;
  const auto elapsed = Clock::now().time_since_epoch();
  return std::chrono::duration_cast<std::chrono::duration<double>>(elapsed).count();
}

struct FaceCapReceiverState {
  std::mutex mutex;
  std::thread worker;
  std::atomic<bool> stop_requested{false};
  bool thread_running = false;
  bool bind_failed = false;
  bool is_listening = false;
  std::string host;
  int port = 0;
  std::string client_address;
  uint64_t packet_count = 0;
  uint64_t dropped_packet_count = 0;
  double last_packet_time = 0.0;
  std::string last_sent_at;
  std::string status_message = "Stopped";
  std::string last_error;
  std::string transport_mode = kReceiverProtocolLiveLinkFace;
  std::string receiver_protocol = kReceiverProtocolLiveLinkFace;
  std::string transport_encoding;
  uint64_t packet_revision = 0;
  uint64_t polled_revision = 0;
  PyObject* latest_packet = nullptr;
  std::vector<unsigned char> recv_scratch;
  SocketHandle server_socket = kInvalidSocket;
  SocketHandle client_socket = kInvalidSocket;
};

FaceCapReceiverState g_receiver_state;

void clear_latest_packet_locked(FaceCapReceiverState* state) {
  if (!state || !state->latest_packet) {
    return;
  }
  Py_DECREF(state->latest_packet);
  state->latest_packet = nullptr;
}

void set_receiver_error(FaceCapReceiverState* state, const std::string& message) {
  if (!state) {
    return;
  }
  std::lock_guard<std::mutex> lock(state->mutex);
  state->last_error = message;
  state->status_message = message.empty() ? state->status_message : message;
}
