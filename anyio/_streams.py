from abc import abstractmethod
from typing import Awaitable

from async_generator import async_generator, yield_

from anyio.abc import ReceiveStream
from anyio.exceptions import DelimiterNotFound, IncompleteRead


class BufferedReceiveStream(ReceiveStream):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._buffer = b''

    @property
    def buffered_data(self) -> bytes:
        return self._buffer

    @abstractmethod
    def _recv(self, max_bytes: int) -> Awaitable[bytes]:
        pass

    async def receive_some(self, max_bytes: int) -> bytes:
        if self._buffer:
            data, self._buffer = self._buffer[:max_bytes], self._buffer[max_bytes:]
            return data

        return await self._recv(max_bytes)

    async def receive_exactly(self, nbytes: int) -> bytes:
        bytes_left = nbytes - len(self._buffer)
        while bytes_left > 0:
            chunk = await self._recv(nbytes)
            if not chunk:
                raise IncompleteRead

            self._buffer += chunk
            bytes_left -= len(chunk)

        result = self._buffer[:nbytes]
        self._buffer = self._buffer[nbytes:]
        return result

    async def receive_until(self, delimiter: bytes, max_size: int) -> bytes:
        delimiter_size = len(delimiter)
        offset = 0
        while True:
            # Check if the delimiter can be found in the current buffer
            index = self._buffer.find(delimiter, offset)
            if index >= 0:
                found = self._buffer[:index]
                self._buffer = self._buffer[index + len(delimiter):]
                return found

            # Check if the buffer is already at or over the limit
            if len(self._buffer) >= max_size:
                raise DelimiterNotFound(max_size)

            # Read more data into the buffer from the socket
            read_size = max_size - len(self._buffer)
            data = await self._recv(read_size)
            if not data:
                raise IncompleteRead

            # Move the offset forward and add the new data to the buffer
            offset = max(len(self._buffer) - delimiter_size + 1, 0)
            self._buffer += data

    @async_generator
    async def receive_chunks(self, max_size: int):
        while True:
            data = await self.receive_some(max_size)
            if data:
                await yield_(data)
            else:
                break

    @async_generator
    async def receive_delimited_chunks(self, delimiter: bytes, max_chunk_size: int):
        while True:
            try:
                chunk = await self.receive_until(delimiter, max_chunk_size)
            except IncompleteRead:
                if self._buffer:
                    raise
                else:
                    break

            await yield_(chunk)
